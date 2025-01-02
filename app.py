from flask import Flask, render_template, request, jsonify, Response, session
from summarize_url import fetch_url_content, generate_all_mcqs, extract_file_content
import json
import queue
import threading
import logging
from threading import Lock
from datetime import datetime, timedelta
import time
import os
from werkzeug.utils import secure_filename
import gc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global rate limiting
REQUESTS_PER_MINUTE = 10
request_timestamps = []
rate_limit_lock = Lock()

def check_rate_limit():
    """Check if we can proceed with the request or need to wait.
    Returns (can_proceed, wait_time_seconds)"""
    with rate_limit_lock:
        now = datetime.now()
        # Remove timestamps older than 1 minute
        global request_timestamps
        request_timestamps = [ts for ts in request_timestamps if now - ts < timedelta(minutes=1)]
        
        # If we haven't hit the limit, add timestamp and proceed
        if len(request_timestamps) < REQUESTS_PER_MINUTE:
            request_timestamps.append(now)
            return True, 0
        
        # Calculate wait time if we've hit the limit
        oldest_timestamp = request_timestamps[0]
        wait_time = 61 - (now - oldest_timestamp).total_seconds()  # 61 to be safe
        return False, max(0, wait_time)

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for session management
progress_queues = {}
queue_lock = Lock()

# Add these configurations after app initialization
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def cleanup_queue(queue_id):
    """Safely remove a queue after ensuring all data has been read."""
    with queue_lock:
        if queue_id in progress_queues:
            logger.info(f"Cleaning up queue {queue_id}")
            del progress_queues[queue_id]

def generate_with_progress(content_or_url, num_questions, queue_id, difficulty='medium', is_url=True):
    try:
        logger.info(f"Starting generation for queue_id: {queue_id} with difficulty: {difficulty}")
        
        # Fetch content if URL provided
        if is_url:
            progress_queues[queue_id].put(('status', 'Fetching content...'))
            content = fetch_url_content(content_or_url)
            
            if not content:
                logger.error("No content fetched from URL")
                progress_queues[queue_id].put(('error', 'Failed to fetch content from URL'))
                return None
                
            if isinstance(content, str) and content.startswith('Error'):
                logger.error(f"Error fetching content: {content}")
                progress_queues[queue_id].put(('error', content))
                return None
        else:
            content = content_or_url

        # Generate MCQs with progress updates
        logger.info("Starting MCQ generation")
        logger.info(f"Will generate {num_questions} questions in batches of 5")
        progress_queues[queue_id].put(('status', f'Initializing generation of {num_questions} {difficulty} level questions...'))
        progress_queues[queue_id].put(('progress', 0))
        
        # Process in smaller batches of 5 questions
        batch_size = 5
        num_batches = (num_questions + batch_size - 1) // batch_size
        logger.info(f"Total batches needed: {num_batches}")
        progress_queues[queue_id].put(('status', f'Starting generation in {num_batches} batches...'))
        
        # Generate all questions at once with proper batch size
        all_questions = generate_all_mcqs(
            content, 
            total_questions=num_questions,
            batch_size=batch_size,
            difficulty=difficulty,
            progress_queue=progress_queues[queue_id]
        )
        
        # Check if we got an error string back
        if isinstance(all_questions, str):
            logger.error(f"Failed to generate questions: {all_questions}")
            progress_queues[queue_id].put(('error', all_questions))
            return
        
        if all_questions:
            logger.info(f"Successfully generated {len(all_questions)} questions")
            questions_with_meta = {
                'questions': all_questions,
                'difficulty': difficulty
            }
            progress_queues[queue_id].put(('complete', questions_with_meta))
        else:
            logger.error("Failed to generate questions")
            progress_queues[queue_id].put(('error', 'Failed to generate questions'))
            
    except Exception as e:
        logger.error(f"Error in generate_with_progress: {str(e)}", exc_info=True)
        progress_queues[queue_id].put(('error', f'An error occurred: {str(e)}'))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html', default_questions=25)

@app.route('/privacy-policy')
def privacy_policy():
    from datetime import datetime
    current_date = datetime.now().strftime('%B %d, %Y')
    return render_template('privacy-policy.html', current_date=current_date)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        # Check rate limit first
        can_proceed, wait_time = check_rate_limit()
        if not can_proceed:
            return jsonify({
                'error': f'Rate limit reached. Please wait {int(wait_time)} seconds before trying again.'
            }), 429
            
        # Check master password
        # master_password = os.getenv('MASTER_PASSWORD')
        # provided_password = request.form.get('master_password')
        
        # if not provided_password or provided_password != master_password:
        #     return jsonify({'error': 'Invalid master password'}), 403
            
        num_questions = int(request.form.get('num_questions', 25))
        difficulty = request.form.get('difficulty', 'medium')
        input_method = request.form.get('input_method', 'url')
        
        logger.info(f"Received request - Method: {input_method}, Questions: {num_questions}, Difficulty: {difficulty}")
        
        content = None
        is_url = True
        
        if input_method == 'url':
            url = request.form.get('url')
            if not url:
                return jsonify({'error': 'Please provide a URL'})
            content = url  # Pass URL directly
        else:
            if 'file' not in request.files:
                return jsonify({'error': 'No file uploaded'})
                
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'})
                
            if not allowed_file(file.filename):
                return jsonify({'error': 'Invalid file format'})
                
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                content = extract_file_content(filepath)
                is_url = False  # Content is already extracted
                os.remove(filepath)  # Clean up the uploaded file
            except Exception as e:
                if os.path.exists(filepath):
                    os.remove(filepath)  # Clean up on error
                raise Exception(f"Error processing file: {str(e)}")
        
        if not content:
            return jsonify({'error': 'Failed to extract content'})
            
        if isinstance(content, str) and content.startswith('Error'):
            return jsonify({'error': content})
        
        # Create a unique queue ID
        queue_id = str(threading.get_ident())
        logger.info(f"Created queue_id: {queue_id}")
        
        with queue_lock:
            progress_queues[queue_id] = queue.Queue()
        
        # Start generation in a background thread
        thread = threading.Thread(
            target=generate_with_progress, 
            args=(content, num_questions, queue_id, difficulty),
            kwargs={'is_url': is_url}
        )
        thread.start()
        
        return jsonify({'queue_id': queue_id})
    except Exception as e:
        logger.error(f"Error in generate endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred: {str(e)}'})

@app.route('/progress/<queue_id>')
def progress(queue_id):
    def generate():
        if queue_id not in progress_queues:
            logger.error(f"Invalid queue_id requested: {queue_id}")
            yield "data: " + json.dumps({"error": "Invalid queue ID"}) + "\n\n"
            return

        try:
            while True:
                try:
                    with queue_lock:
                        if queue_id not in progress_queues:
                            break
                        current_queue = progress_queues[queue_id]
                    
                    msg_type, data = current_queue.get(timeout=1)
                    logger.debug(f"Progress update for {queue_id}: {msg_type}")
                    
                    if msg_type == 'progress':
                        yield "data: " + json.dumps({"progress": data}) + "\n\n"
                    elif msg_type == 'status':
                        yield "data: " + json.dumps({"status": data}) + "\n\n"
                    elif msg_type == 'complete':
                        logger.info(f"Generation complete for {queue_id}")
                        yield "data: " + json.dumps({"complete": True, "questions": data}) + "\n\n"
                        cleanup_queue(queue_id)
                        break
                    elif msg_type == 'error':
                        logger.error(f"Error for {queue_id}: {data}")
                        yield "data: " + json.dumps({"error": data}) + "\n\n"
                        cleanup_queue(queue_id)
                        break
                except queue.Empty:
                    continue
        except Exception as e:
            logger.error(f"Error in progress stream for {queue_id}: {str(e)}", exc_info=True)
            yield "data: " + json.dumps({"error": str(e)}) + "\n\n"
            cleanup_queue(queue_id)

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Get port from environment variable or default to 8000
    port = int(os.environ.get('PORT', 8000))
    # In production, host should be '0.0.0.0' to accept all incoming connections
    app.run(host='0.0.0.0', port=port, debug=False) 