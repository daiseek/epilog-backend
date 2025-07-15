import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateVideosConfig
from google.cloud import storage
import json
import traceback
from datetime import datetime, timedelta, timezone # datetime, timedelta, timezone 임포트
import uuid

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1") # Veo 3 API는 us-central1에서 사용 가능
GOOGLE_CLOUD_GCS_BUCKET = os.getenv("GOOGLE_CLOUD_GCS_BUCKET")

# Google GenAI 클라이언트 초기화
client = genai.Client()

def generate_signed_url(gcs_uri: str, expiration_seconds: int = 3600):
    """
    GCS URI에 대한 서명된 URL을 생성합니다.
    """
    try:
        # gs://bucket-name/object-name 파싱
        path_parts = gcs_uri.replace("gs://", "").split("/", 1)
        bucket_name = path_parts[0]
        blob_name = path_parts[1]

        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds),  # datetime 객체 사용
            method="GET",
        )
        return signed_url
    except Exception as e:
        print(f"Error generating signed URL for {gcs_uri}: {traceback.format_exc()}")
        return None

def generate_video_from_text(prompt: str, title: str):
    """
    텍스트 프롬프트를 사용하여 Veo 3 API로 비디오를 생성합니다.
    """
    try:
        if not GOOGLE_CLOUD_GCS_BUCKET:
            raise Exception("GOOGLE_CLOUD_GCS_BUCKET environment variable is not set.")

        # 고유한 폴더명 또는 파일명 접두사를 위해 UUID 생성
        unique_id = str(uuid.uuid4())
        output_prefix = f"{GOOGLE_CLOUD_GCS_BUCKET.rstrip('/')}/{unique_id}/"

        # 비디오 생성 요청
        operation = client.models.generate_videos(
            model="veo-3.0-generate-preview",
            prompt=prompt,
            config=GenerateVideosConfig(
                output_gcs_uri=output_prefix,
            ),
        )

        # 비디오 생성 완료까지 폴링
        while not operation.done:
            time.sleep(15) # 15초마다 상태 확인
            operation = client.operations.get(operation)

        if operation.response and operation.result.generated_videos:
            video_info = operation.result.generated_videos[0]
            video_uri = video_info.video.uri

            # 서명된 URL 생성
            signed_url = generate_signed_url(video_uri)

            return {"video_uri": video_uri, "signed_url": signed_url, "status": "done"}
        else:
            raise Exception(f"No video generated or unexpected operation result. Operation: {operation}")

    except Exception as e:
        print(f"Error generating video: {traceback.format_exc()}")
        raise