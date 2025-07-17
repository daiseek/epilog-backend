import boto3
import os
from django.conf import settings

# S3 클라이언트 설정 (books와 동일한 방식)
s3 = boto3.client(
    's3',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME
)

def upload_file_to_s3(local_path: str, s3_key: str) -> str:
    # settings 검증
    if not hasattr(settings, 'AWS_STORAGE_BUCKET_NAME') or not settings.AWS_STORAGE_BUCKET_NAME:
        raise ValueError(f"AWS_STORAGE_BUCKET_NAME setting is not configured. Got: {getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)}")
    
    # 파일 존재 확인
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file does not exist: {local_path}")
    
    print(f"Uploading {local_path} to s3://{settings.AWS_STORAGE_BUCKET_NAME}/{s3_key}")
    
    try:
        # 로컬 파일을 S3에 업로드
        s3.upload_file(
            Filename=local_path,
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={'ContentType': 'audio/mpeg'}  # MP3 파일용 Content-Type
        )
        
        # books와 동일한 URL 형식 사용
        url = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{s3_key}"
        print(f"Upload successful. URL: {url}")
        return url
    except Exception as e:
        print(f"S3 upload failed: {type(e).__name__}: {str(e)}")
        raise
