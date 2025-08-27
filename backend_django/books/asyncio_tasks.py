"""Books 앱 asyncio 기반 비동기 작업"""

import asyncio
import tempfile
import os
import base64
import traceback
import aioredis
import json
import uuid
from datetime import datetime
from django.core.files.base import ContentFile
from asgiref.sync import sync_to_async
from .models import Book
from .pdf_utils import extract_text_from_pdf
from .gemini_client import summarize_with_gemini
from .s3_client import upload_to_s3


class AsyncBookProcessor:
    """asyncio 기반 책 PDF 처리 클래스"""
    
    def __init__(self):
        self.redis_url = "redis://backend-redis:6379/3"
    
    async def send_task_event(self, task_id: str, event_type: str, data: dict):
        """
        Redis pub/sub을 통한 비동기 이벤트 전송
        """
        try:
            redis = await aioredis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            channel = f"task-{task_id}"
            message = {
                "event": event_type,
                "data": data
            }
            await redis.publish(channel, json.dumps(message))
            await redis.close()
            print(f"[DEBUG] AsyncIO Redis 이벤트 전송 성공 - 채널: {channel}, 타입: {event_type}")
            return True
        except Exception as e:
            print(f"[DEBUG] AsyncIO Redis 이벤트 전송 실패 - 채널: {channel}, 오류: {str(e)}")
            return False
    
    async def process_pdf_text_extraction(self, pdf_file_content: str, pdf_file_name: str):
        """PDF 텍스트 추출 (I/O bound 작업)"""
        pdf_binary = base64.b64decode(pdf_file_content)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(pdf_binary)
            temp_file_path = temp_file.name
        
        try:
            # 비동기적으로 PDF 텍스트 추출
            with open(temp_file_path, 'rb') as f:
                pdf_file = ContentFile(f.read(), name=pdf_file_name)
            
            # CPU bound 작업을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            extracted_text = await loop.run_in_executor(None, extract_text_from_pdf, pdf_file)
            
            return extracted_text, pdf_file
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    
    async def process_gemini_summary(self, extracted_text: str):
        """Gemini API 요약 (I/O bound 작업)"""
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, summarize_with_gemini, extracted_text)
        return summary
    
    async def process_s3_upload(self, pdf_file):
        """S3 업로드 (I/O bound 작업)"""
        pdf_file.seek(0)
        loop = asyncio.get_event_loop()
        pdf_url = await loop.run_in_executor(None, upload_to_s3, pdf_file)
        return pdf_url
    
    async def process_book_pdf_async(self, book_id: int, pdf_file_content: str, pdf_file_name: str):
        """
        asyncio를 사용한 PDF 파일 비동기 처리
        
        Args:
            book_id: Book 인스턴스 ID
            pdf_file_content: PDF 파일 바이너리 내용 (base64 인코딩된 문자열)
            pdf_file_name: PDF 파일명
        """
        task_id = str(uuid.uuid4())
        
        print(f"[DEBUG] AsyncIO 작업 시작됨 - book_id: {book_id}, task_id: {task_id}")
        
        try:
            # Book 인스턴스 조회 (동기 → 비동기 변환)
            book = await sync_to_async(Book.objects.get)(id=book_id)
            
            # 상태 업데이트
            book.processing_status = 'PROCESSING'
            book.task_id = task_id
            await sync_to_async(book.save)()
            
            print(f"책 PDF 처리 시작 - ID: {book_id}, Task: {task_id}, 제목: {book.title}")
            
            # 작업 시작 이벤트 전송
            await self.send_task_event(task_id, "started", {
                "message": "PDF 처리 시작됨",
                "book_id": book_id,
                "book_title": book.title
            })
            
            # 병렬 처리를 위한 작업들
            print("PDF 텍스트 추출 시작...")
            extracted_text, pdf_file = await self.process_pdf_text_extraction(
                pdf_file_content, pdf_file_name
            )
            print(f"추출된 텍스트 길이: {len(extracted_text)} 문자")
            
            # Gemini 요약과 S3 업로드를 병렬 실행
            print("Gemini API 요약 및 S3 업로드 병렬 시작...")
            summary_task = self.process_gemini_summary(extracted_text)
            s3_upload_task = self.process_s3_upload(pdf_file)
            
            # 두 작업을 병렬로 실행
            summary, pdf_url = await asyncio.gather(summary_task, s3_upload_task)
            
            print(f"요약 완료: {len(summary)} 문자")
            print(f"S3 업로드 완료: {pdf_url}")
            
            # DB 업데이트
            book.content = summary
            book.pdf_url = pdf_url
            book.processing_status = 'COMPLETED'
            book.error_message = None
            await sync_to_async(book.save)()
            
            # 완료 이벤트 전송
            await self.send_task_event(task_id, "completed", {"s3_url": pdf_url})
            
            print(f"✅ 책 PDF 처리 완료 - ID: {book_id}, Task: {task_id}")
            
            return {
                "status": "success",
                "task_id": task_id,
                "book_id": book_id,
                "title": book.title,
                "pdf_url": pdf_url,
                "content_length": len(summary)
            }
            
        except Exception as e:
            error_msg = f"PDF 처리 중 오류 발생: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"❌ 오류 타입: {type(e).__name__}")
            
            # 오류 상태로 DB 업데이트
            try:
                book = await sync_to_async(Book.objects.get)(id=book_id)
                book.processing_status = 'FAILED'
                book.error_message = error_msg
                await sync_to_async(book.save)()
            except:
                pass
            
            # 오류 이벤트 전송
            await self.send_task_event(task_id, "error", {"message": error_msg})
            
            print(f"❌ 상세 스택 트레이스:\n{traceback.format_exc()}")
            
            raise Exception(error_msg)


# 전역 프로세서 인스턴스
book_processor = AsyncBookProcessor()


async def start_book_processing_task(book_id: int, pdf_file_content: str, pdf_file_name: str):
    """
    asyncio 태스크를 시작하는 함수
    """
    task = asyncio.create_task(
        book_processor.process_book_pdf_async(book_id, pdf_file_content, pdf_file_name)
    )
    return task
