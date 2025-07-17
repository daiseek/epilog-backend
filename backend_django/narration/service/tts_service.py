import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ELEVENLABS_API_KEY")

def generate_tts(text, voice_id, output_path, stability=0.5, similarity_boost=0.75):
    print(f"[TTS 요청] text: {repr(text)}, voice_id: {voice_id}, output_path: {output_path}")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost
        }
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 200:
        raise Exception(f"TTS API Error: {response.status_code} - {response.text}")

    # audio 저장
    with open(output_path, "wb") as f:
        f.write(response.content)
