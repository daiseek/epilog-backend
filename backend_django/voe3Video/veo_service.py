import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai.types import GenerateVideosConfig
from google.cloud import storage
import json
import traceback
from datetime import datetime, timedelta, timezone
import uuid

from voe3Video.models import Video # Django Video 모델 임포트: 비디오 메타데이터를 DB에 저장하기 위함

# .env 파일에서 환경 변수를 로드
# 이 파일은 Google Cloud 프로젝트 ID, 위치, GCS 버킷 정보 등 포함.
load_dotenv()

# 환경 변수 설정
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT_ID") # Google Cloud 프로젝트 ID
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1") # Veo 3 API가 사용 가능한 리전,Veo us-central1 말고는 불가
GOOGLE_CLOUD_GCS_BUCKET = os.getenv("GOOGLE_CLOUD_GCS_BUCKET") # 비디오가 저장될 Google Cloud Storage 버킷 경로

# Google GenAI 클라이언트 초기화
# 이 클라이언트를 통해 Veo 3 API에 접근.
# GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI 환경 변수 사용.
client = genai.Client()

# GCS 서명된 URL 생성 함수
# GCS에 저장된 비디오 파일에 대해 일정 시간 동안 유효한 공개 접근 URL을 생성.
# 이는 비디오를 웹에서 직접 재생하거나 다운로드할 때 사용. GCS(Google Cloud Storage)에 저장되는 url이 랑은 별도의 url
def generate_signed_url(gcs_uri: str, expiration_seconds: int = 3600):
    """
    GCS URI에 대한 서명된 URL을 생성. (서명된 URL = 우리가 접속해 영상을 보는 URL)

    Args:
        gcs_uri (str): Google Cloud Storage에 저장된 비디오의 URI (예: gs://bucket-name/object-name).
        expiration_seconds (int): 서명된 URL의 유효 시간 (초 단위). 기본값은 1시간(3600초)입니다.

    Returns:
        str: 생성된 서명된 URL, 또는 오류 발생 시 None.
    """
    try:
        # GCS URI에서 버킷 이름과 객체 이름(blob name)을 파싱.
        # 예: "gs://bucket-name/path/to/video.mp4" -> ("bucket-name", "path/to/video.mp4")
        path_parts = gcs_uri.replace("gs://", "").split("/", 1)
        bucket_name = path_parts[0]
        blob_name = path_parts[1]

        # Google Cloud Storage 클라이언트를 초기화.
        storage_client = storage.Client()
        # "bucket-name"을 통해 지정된 버킷을 가져
        bucket = storage_client.bucket(bucket_name)
        # 버킷 내의 객체(파일)를 참조, 여기선 "path/to/video.mp4"
        blob = bucket.blob(blob_name)

        # 서명된 URL을 생성. 이 URL이 접속해서 영상이 생성되는 URL
        # version="v옴: v4 서명 방식을 사용합니다. (권장)
        # expiration: URL이 만료될 시간 (UTC 기준 datetime 객체).
        # method="GET": GET 요청에 대해서만 유효한 URL을 생성.
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds),  # 현재 UTC 시간 + 유효 시간
            method="GET",
        )
        return signed_url
    except Exception as e:
        # 오류 발생 시 예외처
        print(f"Error generating signed URL for {gcs_uri}: {traceback.format_exc()}")
        return None

# 텍스트를 기반으로 비디오를 생성하는 함수
# Google Cloud Vertex AI의 Veo 3 API를 호출하여 비디오를 생성, 생성된 비디오의 메타데이터를 데이터베이스에 저장.
def generate_video_from_text(prompt: str, title: str, user_id: str = None):
    """
    텍스트 프롬프트를 사용하여 Veo 3 API로 비디오를 생성.

    Args:
        prompt (str): 비디오 생성에 사용될 텍스트 프롬프트.
        title (str): 생성될 비디오의 제목.
        user_id (str, optional): 비디오를 생성하는 사용자의 ID. JWT 인증 시 사용됩니다. 기본값은 None.

    Returns:
        dict: 생성된 비디오의 URI, 서명된 URL, 상태를 포함하는 딕셔너리.
    """
    try:
        # GCS 버킷 환경 변수가 설정 확인.
        if not GOOGLE_CLOUD_GCS_BUCKET:
            raise Exception("GOOGLE_CLOUD_GCS_BUCKET environment variable is not set.")

        # Veo API는 고정된 파일명을 생성하므로 충돌을 피하기 위해 임시 고유 폴더에 비디오를 생성.
        # 따라서 임시 폴더 생성을 위해 UUID 사용
        temp_folder_name = str(uuid.uuid4())
        temp_output_prefix = f"{GOOGLE_CLOUD_GCS_BUCKET.rstrip('/')}/{temp_folder_name}/"

        # Veo 3 모델 로드, 비디오 생성 요청 전송
        operation = client.models.generate_videos(
            model="veo-3.0-generate-preview",
            prompt=prompt,
            config=GenerateVideosConfig(
                output_gcs_uri=temp_output_prefix,
            ),
        )

        # 비디오 생성 완료까지 폴링.
        # 폴링기법, sychronize 등의 기법이 있는데 구현도 간편하고 전송여부를 확인하기 위함
        while not operation.done:
            time.sleep(15)
            operation = client.operations.get(operation)

        # operation이 완료되고 응답 및 생성된 비디오 정보가 있는지 확인.
        if operation.response and operation.result.generated_videos:
            # 2. 생성된 비디오 정보 가져오기
            temp_video_info = operation.result.generated_videos[0]
            temp_video_uri = temp_video_info.video.uri  # 임시 GCS URI

            # 3. GCS에서 파일 이동 및 이름 변경
            storage_client = storage.Client()
            
            # GCS URI에서 버킷 이름과 임시 객체 이름 파싱
            path_parts = temp_video_uri.replace("gs://", "").split("/", 1)
            bucket_name = path_parts[0]
            temp_blob_name = path_parts[1]

            source_bucket = storage_client.bucket(bucket_name)
            source_blob = source_bucket.blob(temp_blob_name)

            # 데이터베이스에서 비디오 개수를 세어 새 파일명 결정
            video_index = Video.objects.count()
            # 최종 저장될 폴더 및 파일명 설정
            final_blob_name = f"generated_videos/video_{video_index}.mp4"
            
            # 파일을 새 위치로 복사(이름 변경)
            destination_blob = source_bucket.copy_blob(
                source_blob, source_bucket, final_blob_name
            )
            
            # 4. 임시 파일 및 폴더 삭제
            source_blob.delete() # 원본 임시 파일 삭제
            # 임시 폴더 내 다른 파일(예: 메타데이터 파일)이 있을 수 있으므로, 접두사로 검색하여 모두 삭제
            blobs_to_delete = list(source_bucket.list_blobs(prefix=f"{temp_folder_name}/"))
            for blob in blobs_to_delete:
                blob.delete()

            # 5. 최종 URI로 데이터베이스에 저장 및 반환
            final_video_uri = f"gs://{bucket_name}/{final_blob_name}"
            signed_url = generate_signed_url(final_video_uri)

            Video.objects.create(
                video_uri=final_video_uri,
                prompt=prompt,
                title=title,
                user_id=user_id
            )

            return {"video_uri": final_video_uri, "signed_url": signed_url, "status": "done"}
        else:
            raise Exception(f"No video generated or unexpected operation result. Operation: {operation}")

    except Exception as e:
        print(f"Error generating video: {traceback.format_exc()}")
        raise

# 비디오 목록을 조회하는 함수
# 데이터베이스에 저장된 비디오 메타데이터를 조회하고, 각 비디오에 대한 서명된 URL을 생성하여 반환.
def list_videos(user_id: str = None):
    """
    데이터베이스에서 비디오 목록을 조회하고 서명된 URL을 생성합니다.

    Args:
        user_id (str, optional): 특정 사용자의 비디오만 필터링하기 위한 사용자 ID. 기본값은 None.

    Returns:
        list: 비디오 정보(ID, URI, 서명된 URL, 프롬프트, 제목, 사용자 ID, 생성 시간) 딕셔너리 리스트.
    """
    try:
        # user_id가 제공되면 해당 사용자의 비디오만 필터링하고, 그렇지 않으면 모든 비디오를 조회. (마이페이지 기능과 전체조회 기능)
        # 'created_at' 필드를 기준으로 최신순으로 정렬.
        if user_id:
            videos_from_db = Video.objects.filter(user_id=user_id).order_by('-created_at')
        else:
            videos_from_db = Video.objects.all().order_by('-created_at')

        videos_data = []
        # 조회된 각 비디오 객체에 대해 정보를 추출하고 서명된 URL 조회.
        for video in videos_from_db:
            signed_url = generate_signed_url(video.video_uri)
            videos_data.append({
                "id": video.id, # 비디오의 고유 ID
                "video_uri": video.video_uri, # GCS에 저장된 비디오의 URI
                "signed_url": signed_url,   # 실제 영상 조회 가능한 HTTP URL
                "prompt": video.prompt, # 비디오 생성에 사용된 프롬프트
                "title": video.title, # 비디오 제목
                "user_id": video.user_id, # 비디오를 생성한 사용자 ID
                "created_at": video.created_at.isoformat(), # 비디오 생성 시간
            })
        return videos_data
    except Exception as e:
        # 오류 발생 시 예외처리
        print(f"Error listing videos: {traceback.format_exc()}")
        raise
