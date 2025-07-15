import requests
import os
import time
from dotenv import load_dotenv

load_dotenv()

TYPECAST_API_KEY = os.getenv("TYPECAST_API_KEY")
TYPECAST_API_URL = "https://typecast.ai"

def get_actors():
    headers = {
        "Authorization": f"Bearer {TYPECAST_API_KEY}",
    }
    response = requests.get(f"{TYPECAST_API_URL}/api/actor", headers=headers)
    response.raise_for_status()
    return response.json()

def text_to_speech(text, actor_id, title):
    headers = {
        "Authorization": f"Bearer {TYPECAST_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "lang": "auto",
        "actor_id": actor_id,
        "xapi_hd": True,
        "model_version": "latest"
    }
    
    # 1. Request Speech Synthesis
    response = requests.post(f"{TYPECAST_API_URL}/api/speak", headers=headers, json=data)
    response.raise_for_status()
    
    speak_url = response.json().get("result", {}).get("speak_v2_url")
    if not speak_url:
        raise Exception("Failed to get speak_v2_url")

    # 2. Poll for Status
    for _ in range(120):  # Poll for up to 2 minutes
        response = requests.get(speak_url, headers=headers)
        response.raise_for_status()
        status = response.json().get("result", {}).get("status")
        
        if status == "done":
            audio_download_url = response.json().get("result", {}).get("audio_download_url")
            if not audio_download_url:
                raise Exception("Failed to get audio_download_url")
            return {"audio_download_url": audio_download_url}
        
        elif status == "error":
            raise Exception("Speech synthesis failed")
            
        time.sleep(1)
        
    raise Exception("Polling timed out")