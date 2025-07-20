

from celery import shared_task
import os
import tempfile
import subprocess
from google.cloud import storage
from .veo_service import generate_signed_url # generate_signed_url 함수 재사용
from .models import Video # Video 모델 임포트
from characters.models import Character

# 환경 변수 설정 (veo_service.py에서 가져옴)
import os
from dotenv import load_dotenv
load_dotenv()
GOOGLE_CLOUD_GCS_BUCKET = os.getenv("GOOGLE_CLOUD_GCS_BUCKET")

@shared_task
def create_video_for_scene(character_id, prompt, title):
    """
    Celery 작업으로 비디오 생성을 비동기적으로 처리합니다.
    """
    try:
        # character_id를 사용하여 generate_video_from_text 함수를 호출합니다.
        generate_video_from_text(prompt=prompt, title=title, character_id=character_id)
    except Character.DoesNotExist:
        # 캐릭터를 찾을 수 없는 경우 로그를 남기거나 오류 처리를 할 수 있습니다.
        print(f"Error: Character with id {character_id} not found.")
    except Exception as e:
        # 기타 예외 처리
        print(f"Error generating video for character {character_id}: {e}")

@shared_task
def combine_videos_task(video_uris, output_title, user_id=None, character_id=None):
    """
    여러 GCS 비디오 URI를 받아 하나의 비디오로 합치고 GCS에 업로드합니다.
    """
    storage_client = storage.Client()
    bucket_name = GOOGLE_CLOUD_GCS_BUCKET.replace("gs://", "").rstrip('/')
    bucket = storage_client.bucket(bucket_name)

    temp_files = []
    input_file_list_path = None
    combined_video_path = None

    try:
        # 1. GCS에서 각 비디오 다운로드
        for i, uri in enumerate(video_uris):
            blob_name = uri.replace(f"gs://{bucket_name}/", "")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{i}.mp4")
            temp_file.close()
            temp_files.append(temp_file.name)

            blob = bucket.blob(blob_name)
            blob.download_to_filename(temp_file.name)
            print(f"Downloaded {uri} to {temp_file.name}")

        # 2. FFmpeg를 사용하여 비디오 합치기
        # FFmpeg concat demuxer를 위한 파일 목록 생성
        input_file_list_path = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        for f in temp_files:
            input_file_list_path.write(f"file '{f}'\n".encode('utf-8'))
        input_file_list_path.close()
        print(f"Created ffmpeg input list: {input_file_list_path.name}")

        combined_video_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        combined_video_path.close()
        
        ffmpeg_command = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", input_file_list_path.name,
            "-c", "copy",
            "-y", # Overwrite output files without asking
            combined_video_path.name
        ]
        print(f"Running ffmpeg command: {' '.join(ffmpeg_command)}")
        subprocess.run(ffmpeg_command, check=True, capture_output=True)
        print(f"Combined video saved to {combined_video_path.name}")

        # 3. 합쳐진 비디오를 GCS에 업로드
        base_output_name = output_title.replace(' ', '_')
        extension = ".mp4"
        counter = 0
        output_blob_name = f"combined_videos/{base_output_name}{extension}"

        while bucket.blob(output_blob_name).exists():
            counter += 1
            output_blob_name = f"combined_videos/{base_output_name}_{counter}{extension}"
        
        output_blob = bucket.blob(output_blob_name)
        output_blob.upload_from_filename(combined_video_path.name)
        final_gcs_uri = f"gs://{bucket_name}/{output_blob_name}"
        print(f"Uploaded combined video to {final_gcs_uri}")

        # 4. 데이터베이스 업데이트 (선택 사항: 필요에 따라 Video 모델에 저장)
        signed_url = generate_signed_url(final_gcs_uri)
        print(f"Combined video signed URL: {signed_url}") # 추가된 라인
        Video.objects.create(
            video_uri=final_gcs_uri,
            prompt=f"Combined video: {', '.join(video_uris)}",
            title=output_title,
            user_id=user_id,
            character_id=character_id,
            # 기타 필요한 필드 추가
        )
        print(f"Combined video metadata saved to DB: {output_title}")

        return {"status": "success", "gcs_uri": final_gcs_uri, "signed_url": signed_url}

    except subprocess.CalledProcessError as e:
        print(f"FFmpeg command failed: {e}")
        print(f"Stdout: {e.stdout.decode()}")
        print(f"Stderr: {e.stderr.decode()}")
        raise
    except Exception as e:
        print(f"Error combining videos: {e}")
        raise
    finally:
        # 5. 임시 파일 정리
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
                print(f"Cleaned up temporary file: {f}")
        if input_file_list_path and os.path.exists(input_file_list_path.name):
            os.remove(input_file_list_path.name)
            print(f"Cleaned up temporary input list: {input_file_list_path.name}")
        if combined_video_path and os.path.exists(combined_video_path.name):
            os.remove(combined_video_path.name)
            print(f"Cleaned up temporary combined video: {combined_video_path.name}")
