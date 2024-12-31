# MCQ Generator (𝘔𝘊𝘘 𝘎𝘌𝘕 𝘈𝘐)

An AI-powered Multiple Choice Question (MCQ) generator that creates questions from URLs or uploaded files (PDF, Word, Text).

## Features

- Generate MCQs from:
  - Web URLs
  - PDF files
  - Word documents (.doc, .docx)
  - Text files
- Multiple difficulty levels:
  - Easy
  - Medium
  - Hard
  - Very Hard
- Interactive quiz interface with:
  - Real-time progress tracking
  - Timer
  - Question navigation
  - Answer review
- Detailed results with:
  - Score calculation
  - Time taken
  - Correct/incorrect answers
  - PDF download option
- Password protection to prevent abuse
- Responsive design

## Tech Stack

- Backend: Flask (Python)
- Frontend: HTML, CSS, JavaScript
- AI: Google's Gemini Pro API
- PDF Generation: jsPDF
- Styling: Bootstrap 5
- Deployment: Render

## Prerequisites

- Python 3.11.7
- Google Gemini API key
- Modern web browser

## Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd mcq-generator
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp example.env .env
```
Edit `.env` file and add:
- Your Gemini API key
- Master password for question generation

## Local Development

Run the application:
```bash
python app.py
```
Access at: http://localhost:8000

## Deployment on Render

1. Push code to GitHub:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

2. On Render:
   - Create new Web Service
   - Connect GitHub repository
   - Configure build settings:
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `gunicorn app:app`
   - Add environment variables:
     - `GEMINI_API_KEY`
     - `MASTER_PASSWORD`
   - Deploy

## Usage

1. Access the web interface
2. Choose input method (URL or file upload)
3. Set number of questions and difficulty level
4. Enter master password
5. Generate questions
6. Start the quiz
7. Complete the test
8. Review results and download PDF

## Security Features

- Master password protection
- Secure file handling
- Session management
- Input validation
- Error handling

## Contributing

1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request

## License

MIT License

## Made with 💙 by V

For support or questions, please open an issue on GitHub. 