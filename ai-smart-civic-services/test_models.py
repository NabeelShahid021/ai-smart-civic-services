import httpx
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

for model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro", "gemini-pro"]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Say hello in JSON format: {\"message\": \"hello\"}"}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        print(f"Model {model}: status={r.status_code}, body={r.text[:150]}")
    except Exception as e:
        print(f"Model {model} error: {e}")
