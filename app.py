from flask import Flask, render_template, request, jsonify, Response, session
from summarize_url import fetch_url_content, generate_all_mcqs
import json
import queue
import threading
import logging
from threading import Lock
from datetime import datetime
import time

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

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for session management
progress_queues = {}
queue_lock = Lock()

def cleanup_queue(queue_id):
    """Safely remove a queue after ensuring all data has been read."""
    with queue_lock:
        if queue_id in progress_queues:
            logger.info(f"Cleaning up queue {queue_id}")
            del progress_queues[queue_id]

def generate_with_progress(url, num_questions, queue_id, difficulty='medium'):
    try:
        logger.info(f"Starting generation for queue_id: {queue_id} with difficulty: {difficulty}")
        
        # Fetch content
        progress_queues[queue_id].put(('status', 'Fetching content...'))
        content = fetch_url_content(url)
        
        if not content:
            logger.error("No content fetched from URL")
            progress_queues[queue_id].put(('error', 'Failed to fetch content from URL'))
            return None
            
        if isinstance(content, str) and content.startswith('Error'):
            logger.error(f"Error fetching content: {content}")
            progress_queues[queue_id].put(('error', content))
            return None

        # Generate MCQs with progress updates
        logger.info("Starting MCQ generation")
        questions = generate_all_mcqs(content, total_questions=num_questions, difficulty=difficulty, progress_queue=progress_queues[queue_id])
        
        if questions:
            logger.info(f"Successfully generated {len(questions)} questions")
            # Add difficulty to questions metadata
            questions_with_meta = {
                'questions': questions,
                'difficulty': difficulty
            }
            progress_queues[queue_id].put(('complete', questions_with_meta))
        else:
            logger.error("Failed to generate questions")
            progress_queues[queue_id].put(('error', 'Failed to generate questions'))
    except Exception as e:
        logger.error(f"Error in generate_with_progress: {str(e)}", exc_info=True)
        progress_queues[queue_id].put(('error', f'An error occurred: {str(e)}'))

@app.route('/')
def index():
    return render_template('index.html', default_questions=25)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        url = request.form.get('url')
        num_questions = int(request.form.get('num_questions', 25))  # Default to 25 questions
        difficulty = request.form.get('difficulty', 'medium')  # Get difficulty level
        
        logger.info(f"Received request for URL: {url}, Questions: {num_questions}, Difficulty: {difficulty}")
        
        if not url:
            return jsonify({'error': 'Please provide a URL'})
        
        # Create a unique queue ID
        queue_id = str(threading.get_ident())
        logger.info(f"Created queue_id: {queue_id}")
        
        with queue_lock:
            progress_queues[queue_id] = queue.Queue()
        
        # Start generation in a background thread
        thread = threading.Thread(target=generate_with_progress, args=(url, num_questions, queue_id, difficulty))
        thread.start()
        
        return jsonify({'queue_id': queue_id})
    except Exception as e:
        logger.error(f"Error in generate endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': f'An error occurred: {str(e)}'})

@app.route('/start-test', methods=['POST'])
def start_test():
    try:
        data = request.get_json()
        questions = data.get('questions', [])
        difficulty = data.get('difficulty', 'medium')  # Get difficulty from request
        
        if not questions:
            return jsonify({'error': 'No questions provided'}), 400
            
        # Store in session
        session['questions'] = questions
        session['start_time'] = time.time()
        session['difficulty'] = difficulty  # Store difficulty in session
        
        return jsonify({'questions': questions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/submit-answer', methods=['POST'])
def submit_answer():
    data = request.json
    question_index = str(data.get('questionIndex'))  # Convert to string for consistent key type
    answer = data.get('answer')
    
    if 'answers' not in session:
        session['answers'] = {}
    
    # Update the answers in session
    answers = dict(session['answers'])  # Create a copy of the dict
    answers[question_index] = answer
    session['answers'] = answers  # Reassign to trigger session update
    
    logger.info(f"Saved answer for question {question_index}: {answer}")
    logger.info(f"Current session answers: {session['answers']}")
    
    return jsonify({'success': True})

@app.route('/finish-test', methods=['POST'])
def finish_test():
    try:
        data = request.get_json()
        user_answers = data.get('answers', {})
        
        # Get questions from session
        questions = session.get('questions', [])
        if not questions:
            return jsonify({'error': 'No test in progress'}), 400
            
        # Calculate duration
        start_time = session.get('start_time')
        duration = time.time() - start_time if start_time else 0
        
        # Get difficulty level from session
        difficulty = session.get('difficulty', 'medium')  # Default to medium if not specified
        
        # Process results
        correct_answers = 0
        processed_questions = []
        
        for i, question in enumerate(questions):
            user_answer = user_answers.get(str(i))
            is_correct = user_answer == question['correct_answer']
            if is_correct:
                correct_answers += 1
                
            processed_questions.append({
                'question': question['question'],
                'options': question['options'],
                'user_answer': user_answer,
                'correct_answer': question['correct_answer'],
                'is_correct': is_correct
            })
        
        results = {
            'total_questions': len(questions),
            'correct_answers': correct_answers,
            'duration': duration,
            'questions': processed_questions,
            'difficulty': difficulty  # Include difficulty in results
        }
        
        # Clear session
        session.pop('questions', None)
        session.pop('start_time', None)
        session.pop('difficulty', None)
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/get-answers', methods=['GET'])
def get_answers():
    """Get existing answers from session."""
    if 'answers' not in session:
        return jsonify({'answers': {}})
    return jsonify({'answers': session['answers']})

if __name__ == '__main__':
    app.run(debug=True, port=8000) 