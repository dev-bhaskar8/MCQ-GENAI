# URL Content MCQ Generator

This script uses Gemini AI to generate Multiple Choice Questions (MCQs) from web page content. It fetches content from a given URL and generates comprehensive MCQs with 6 options each.

## Features

- Fetches and processes content from any webpage
- Generates 5 multiple choice questions
- Each question includes:
  - 4 specific answer options (a, b, c, d)
  - "All of the above" option (e)
  - "None of these" option (f)
- Automatically removes irrelevant HTML elements
- Cleans and formats the text content
- Handles errors gracefully
- Uses `.env` file for secure API key management

## Setup

1. Create and activate a virtual environment:
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# .\venv\Scripts\activate
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root and add your Gemini API key:
```bash
echo "GEMINI_API_KEY=your-api-key-here" > .env
```

## Usage

Run the script:
```bash
python summarize_url.py
```

When prompted, enter the URL of the webpage. The script will:
1. Fetch the content from the URL
2. Clean and extract the text
3. Generate 5 MCQs using Gemini AI
4. Display the questions with all options and correct answers 