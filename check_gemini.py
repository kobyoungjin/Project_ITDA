import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv(dotenv_path=".env")
api_key = os.getenv("GEMINI_API_KEY")

if not api_key or api_key == "your_gemini_api_key_here":
    print("API_KEY_MISSING")
    exit(1)

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-flash-latest")

try:
    response = model.generate_content("Hello! Can you reply in Korean with just '네, 제미나이 연결이 완벽하게 정상입니다!'?")
    print("SUCCESS")
    print("Response:", response.text.strip())
except Exception as e:
    print("ERROR")
    print(str(e))
