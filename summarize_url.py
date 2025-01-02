import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import json
import re
from tqdm import tqdm
import PyPDF2
import io
import time
from datetime import datetime, timedelta
import docx
import chardet
import gc

# Load environment variables from .env file
load_dotenv()

# Rate limiting settings
REQUESTS_PER_MINUTE = 10  # Setting to 10 RPM
request_timestamps = []

def wait_for_rate_limit():
    """Wait if necessary to comply with rate limits."""
    global request_timestamps
    now = datetime.now()
    
    # Remove timestamps older than 1 minute
    request_timestamps = [ts for ts in request_timestamps if now - ts < timedelta(minutes=1)]
    
    # If we've made too many requests in the last minute, wait
    if len(request_timestamps) >= REQUESTS_PER_MINUTE:
        # Calculate wait time
        oldest_timestamp = request_timestamps[0]
        wait_time = 61 - (now - oldest_timestamp).total_seconds()  # 61 to be safe
        if wait_time > 0:
            return wait_time
    
    return 0

def is_pdf_url(url):
    """Check if the URL points to a PDF file."""
    url_lower = url.lower()
    return url_lower.endswith('.pdf') or '/pdf/' in url_lower or 'type=pdf' in url_lower

def extract_pdf_content(response):
    """Extract text content from a PDF file."""
    try:
        pdf_file = io.BytesIO(response.content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        # Use list comprehension and join instead of string concatenation
        text = '\n'.join(page.extract_text() for page in pdf_reader.pages)
        
        # Limit content size to prevent memory issues
        max_chars = 100000
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.warning(f"PDF content truncated to {max_chars} characters")
            
        return text.strip()
    except Exception as e:
        return f"Error extracting PDF content: {str(e)}"

def fetch_url_content(url):
    """Fetch content from URL, handling both HTML and PDF content."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # Handle PDF files
        if is_pdf_url(url):
            return extract_pdf_content(response)

        # Handle HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unnecessary elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "meta", "link"]):
            element.decompose()
            
        # Get text content
        text = soup.get_text()
        
        # Clean up text
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # Content length validation
        text = text.strip()
        if len(text) < 100:
            raise ValueError("Extracted content seems too short (less than 100 characters)")
        if len(text) > 100000:
            text = text[:100000]
            print("Warning: Content truncated to 100,000 characters")
            
        return text
    except requests.Timeout:
        return "Error: URL request timed out. Please try again or check your internet connection."
    except requests.ConnectionError:
        return "Error: Failed to connect to the URL. Please check your internet connection."
    except requests.RequestException as e:
        return f"Error fetching URL: {str(e)}"
    except Exception as e:
        return f"Error processing content: {str(e)}"

def extract_json_from_text(text):
    """Extract JSON array from text, handling potential formatting issues."""
    try:
        # Try to find JSON array in the text
        match = re.search(r'\[.*\]', text.replace('\n', ' '), re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except:
        return None

def validate_api_key(api_key):
    """Validate the Gemini API key format and configuration."""
    if not api_key:
        return False, "Error: GEMINI_API_KEY not found in .env file"
    if not api_key.startswith('AI'):
        return False, "Error: Invalid API key format. Gemini API keys should start with 'AI'"
    return True, None

def generate_mcqs_batch(content, start_num, batch_size=5, difficulty='medium', progress_queue=None):
    """Generate MCQs with batch size optimized for flash model's 8k token limit."""
    api_key = os.getenv("GEMINI_API_KEY")
    
    # Validate API key
    is_valid, error_msg = validate_api_key(api_key)
    if not is_valid:
        return error_msg
    
    # Handle rate limiting
    wait_time = wait_for_rate_limit()
    if wait_time > 0:
        if progress_queue:
            progress_queue.put(('status', f'Rate limit reached. Waiting {int(wait_time)} seconds...'))
        time.sleep(wait_time)
    
    try:
        genai.configure(api_key=api_key)

        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,  # Maximum allowed for flash model (must be less than 8193)
        }

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-exp",
            generation_config=generation_config,
        )

        # Split content into smaller chunks if it's too long
        content_words = content.split()
        max_words = 2000  # Reduced for flash model's 8k token limit
        if len(content_words) > max_words:
            content = ' '.join(content_words[:max_words])

        # Detailed difficulty-specific guidelines
        difficulty_guidelines = {
            'easy': """
                - Focus on basic facts and definitions from the text
                - Use straightforward, simple language in questions and options
                - Test direct recall and basic comprehension
                - Make distractors clearly different from correct answers
                - Avoid complex terminology or intricate concepts
                - Include obvious incorrect options
                - Questions should be answerable with surface-level understanding
            """,
            'medium': """
                - Test both recall and application of concepts
                - Include some analytical thinking
                - Use moderate complexity in language and concepts
                - Create plausible distractors that require careful consideration
                - Mix straightforward and moderately challenging questions
                - Test relationships between different concepts
                - Require understanding beyond just memorization
            """,
            'hard': """
                - Focus on complex relationships between concepts
                - Test deep understanding and analysis
                - Include application to new scenarios
                - Create sophisticated distractors that test fine distinctions
                - Require critical thinking and evaluation
                - Include questions that combine multiple concepts
                - Test ability to make informed judgments
            """,
            'very_hard': """
                - Test expert-level understanding and synthesis
                - Require integration of multiple complex concepts
                - Include nuanced distinctions between options
                - Create extremely challenging distractors
                - Test ability to evaluate complex scenarios
                - Require deep subject matter expertise
                - Include advanced application and analysis
            """
        }

        prompt = f"""You are an expert at creating multiple choice questions. Create exactly {batch_size} {difficulty} level questions from the given content.
        Make these questions unique and different from questions {start_num-batch_size+1} to {start_num}.
        
        Difficulty Level: {difficulty}
        {difficulty_guidelines[difficulty]}

        Important Instructions:
        1. Return ONLY a JSON array containing {batch_size} question objects
        2. Each question MUST have:
           - 4 specific answer options (a, b, c, d)
           - Option e: "All of the above" (use ONLY when all previous options are correct)
           - Option f: "None of these" (use ONLY when all previous options are incorrect)
        3. Use this exact JSON structure and format your response as pure JSON:
        [
            {{
                "question": "Question text here (keep it concise, around 20-30 words)",
                "options": {{
                    "a": "First option (keep it concise, 10-15 words)",
                    "b": "Second option (keep it concise, 10-15 words)",
                    "c": "Third option (keep it concise, 10-15 words)",
                    "d": "Fourth option (keep it concise, 10-15 words)",
                    "e": "All of the above",
                    "f": "None of these"
                }},
                "correct_answer": "a"
            }}
        ]

        Guidelines for questions:
        - Keep questions concise (20-30 words max)
        - Keep options brief (10-15 words max)
        - Make questions clear and unambiguous
        - IMPORTANT: For approximately 95% of questions, distribute correct answers evenly among options a, b, c, and d
        - IMPORTANT: For about 2.5% of questions, make option "e" (All of the above) the correct answer
        - IMPORTANT: For about 2.5% of questions, make option "f" (None of these) the correct answer
        - CRITICAL: When using option "e" (All of the above):
          * ONLY use when options a, b, c, and d are ALL valid correct statements
          * Do NOT include any variations like "All the above" or similar phrases in other options
        - CRITICAL: When using option "f" (None of these):
          * ONLY use when options a, b, c, and d are ALL incorrect statements
          * Do NOT include any variations like "None of the above" or similar phrases in other options
        - Questions should test understanding, not just memorization
        - Cover different aspects of the content
        - Avoid repetitive or similar questions

        Content to generate questions from:
        {content}

        Remember: 
        - Return ONLY the JSON array with no additional text or explanation
        - Generate exactly {batch_size} unique questions
        - Ensure proper JSON formatting
        - Each question must have all 6 options (a through f)
        - Keep questions and options concise to fit more in the batch
        - Use options e and f sparingly (about 5% of questions combined)
        - NEVER duplicate "All of the above" or "None of these" in other options"""

        # Record this request
        request_timestamps.append(datetime.now())
        
        response = model.generate_content(prompt)
        response_text = response.text
        
        # Try to parse the direct response first
        try:
            questions = json.loads(response_text)
            # Validate the number of questions
            if len(questions) != batch_size:
                raise ValueError(f"Expected {batch_size} questions, got {len(questions)}")
            return questions
        except json.JSONDecodeError:
            # Try to extract JSON from the text
            questions = extract_json_from_text(response_text)
            if questions and len(questions) == batch_size:
                return questions
            
            # If still no valid JSON or wrong number of questions, try one more time with a simpler prompt
            wait_time = wait_for_rate_limit()
            if wait_time > 0:
                if progress_queue:
                    progress_queue.put(('status', f'Rate limit reached. Waiting {int(wait_time)} seconds...'))
                time.sleep(wait_time)
            
            request_timestamps.append(datetime.now())
            prompt_retry = f"""Convert this into a valid JSON array with exactly {batch_size} questions:
            {response_text}
            Format as pure JSON array only."""
            
            response_retry = model.generate_content(prompt_retry)
            try:
                questions = json.loads(response_retry.text)
                if len(questions) == batch_size:
                    return questions
                raise ValueError(f"Expected {batch_size} questions, got {len(questions)}")
            except:
                return f"Error: Failed to generate valid MCQs for batch {start_num//batch_size + 1}"
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            return "Error: API rate limit reached. Please try again in a minute."
        elif "invalid_api_key" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return "Error: Invalid API key. Please check your GEMINI_API_KEY in the .env file."
        elif "permission_denied" in error_msg.lower():
            return "Error: Permission denied. Please make sure your API key has the necessary permissions."
        return f"Error generating MCQs batch {start_num//batch_size + 1}: {error_msg}"

def generate_all_mcqs(content, total_questions=25, batch_size=5, difficulty='medium', progress_queue=None):
    """Generate MCQs with optimized rate limit handling."""
    all_questions = []
    num_batches = (total_questions + batch_size - 1) // batch_size
    
    if progress_queue:
        progress_queue.put(('status', f'Starting generation of {total_questions} {difficulty} level MCQs...'))
        progress_queue.put(('progress', 0))  # Initialize progress
    
    # Dynamic delay calculation based on REQUESTS_PER_MINUTE
    delay_time = (60.0 / REQUESTS_PER_MINUTE)  # Convert RPM to seconds per request
    
    # Limit content size for API requests
    max_content_chars = 100000
    if len(content) > max_content_chars:
        content = content[:max_content_chars]
        logger.warning(f"Content truncated to {max_content_chars} characters for API processing")
    
    try:
        for i in range(num_batches):
            current_batch = i + 1
            start_num = i * batch_size
            current_batch_size = min(batch_size, total_questions - start_num)
            
            # Add smart delay between batches
            if i > 0:
                delay_message = f'Pacing requests... waiting {delay_time:.1f} seconds before next batch'
                if progress_queue:
                    progress_queue.put(('status', delay_message))
                time.sleep(delay_time)
            
            if progress_queue:
                progress_queue.put(('status', f'Processing batch {current_batch} of {num_batches} ({current_batch_size} questions)...'))
            
            batch_questions = generate_mcqs_batch(content, start_num, current_batch_size, difficulty, progress_queue)
            
            if isinstance(batch_questions, str):  # Error occurred
                error_msg = batch_questions
                if "rate limit" in error_msg.lower():
                    # If we hit rate limit, use exponential backoff
                    retry_wait = 15
                    max_retries = 3
                    
                    for retry in range(max_retries):
                        retry_message = f'Rate limit hit. Waiting {retry_wait} seconds before retry {retry + 1}/{max_retries}...'
                        if progress_queue:
                            progress_queue.put(('status', retry_message))
                        time.sleep(retry_wait)
                        retry_wait *= 2
                        
                        # Retry the batch
                        batch_questions = generate_mcqs_batch(content, start_num, current_batch_size, difficulty, progress_queue)
                        if not isinstance(batch_questions, str):  # Success
                            break
                    
                    if isinstance(batch_questions, str):  # Still failed after retries
                        if progress_queue:
                            progress_queue.put(('error', batch_questions))
                        return batch_questions
                else:
                    if progress_queue:
                        progress_queue.put(('error', batch_questions))
                    return batch_questions
            
            all_questions.extend(batch_questions)
            
            # Update progress after each batch
            if progress_queue:
                progress = (current_batch * 100) // num_batches
                progress_queue.put(('progress', progress))
                progress_queue.put(('status', f'Completed batch {current_batch} of {num_batches} successfully'))
            
            # Force garbage collection after each batch
            gc.collect()
    
    except Exception as e:
        logger.error(f"Error in generate_all_mcqs: {str(e)}")
        if progress_queue:
            progress_queue.put(('error', f'An error occurred: {str(e)}'))
        return str(e)
    
    if progress_queue:
        progress_queue.put(('progress', 100))  # Ensure we reach 100%
        progress_queue.put(('status', f'Successfully generated all {len(all_questions)} questions!'))
    
    return all_questions

def display_mcqs(questions):
    if isinstance(questions, str):
        print(questions)
        return
        
    print("\nGenerated Multiple Choice Questions:")
    print("=" * 80)
    
    for i, q in enumerate(questions, 1):
        print(f"\nQuestion {i}:")
        print(q["question"])
        print("\nOptions:")
        for opt, text in q["options"].items():
            print(f"{opt}) {text}")
        print(f"\nCorrect Answer: {q['correct_answer']}")
        print("-" * 80)

def read_pdf_content(file_path):
    """Extract text content from a PDF file."""
    try:
        content = []
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            # Process pages in chunks to manage memory
            chunk_size = 10
            for i in range(0, len(pdf_reader.pages), chunk_size):
                chunk = pdf_reader.pages[i:i+chunk_size]
                content.extend(page.extract_text() for page in chunk)
                gc.collect()  # Clear memory after each chunk
                
        text = '\n'.join(content)
        # Limit content size
        max_chars = 100000
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.warning(f"PDF content truncated to {max_chars} characters")
            
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def read_docx_content(file_path):
    """Extract text content from a Word document."""
    doc = docx.Document(file_path)
    content = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            content.append(paragraph.text)
    return ' '.join(content)

def read_text_file(file_path):
    """Extract text content from a text file with encoding detection."""
    with open(file_path, 'rb') as file:
        raw_data = file.read()
        detected = chardet.detect(raw_data)
        encoding = detected['encoding']
    
    with open(file_path, 'r', encoding=encoding) as file:
        return file.read()

def extract_file_content(file_path):
    """Extract content from a file based on its extension."""
    file_extension = file_path.lower().split('.')[-1]
    
    if file_extension == 'pdf':
        return read_pdf_content(file_path)
    elif file_extension in ['doc', 'docx']:
        return read_docx_content(file_path)
    elif file_extension == 'txt':
        return read_text_file(file_path)
    else:
        raise ValueError(f"Unsupported file format: .{file_extension}")

def main():
    url = input("Enter the URL to generate MCQs from: ")
    print("\nFetching content...")
    content = fetch_url_content(url)
    
    if content.startswith("Error"):
        print(content)
        return
    
    questions = generate_all_mcqs(content)
    
    if questions:
        print(f"\nSuccessfully generated {len(questions)} questions!")
        save = input("\nWould you like to save the questions to a file? (y/n): ").lower()
        if save == 'y':
            filename = input("Enter filename (default: mcqs.json): ").strip() or "mcqs.json"
            with open(filename, 'w') as f:
                json.dump(questions, f, indent=2)
            print(f"\nQuestions saved to {filename}")
        
        display = input("\nWould you like to display all questions? (y/n): ").lower()
        if display == 'y':
            display_mcqs(questions)

if __name__ == "__main__":
    main() 