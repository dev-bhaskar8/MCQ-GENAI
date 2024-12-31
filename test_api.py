import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

def test_api_key():
    api_key = os.getenv("GEMINI_API_KEY")
    print(f"API Key found: {'Yes' if api_key else 'No'}")
    print(f"API Key starts with: {api_key[:15]}..." if api_key else "No API key")
    
    try:
        # Configure the API
        genai.configure(api_key=api_key)
        
        # Try a simple generation
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Say 'Hello, testing!'")
        
        print("\nAPI Test Result:")
        print("✓ Successfully connected to Gemini API")
        print("✓ Model response:", response.text)
        return True
    except Exception as e:
        print("\nAPI Test Error:")
        print("✗ Failed to connect to Gemini API")
        print("Error message:", str(e))
        return False

if __name__ == "__main__":
    print("Testing Gemini API connection...")
    test_api_key() 