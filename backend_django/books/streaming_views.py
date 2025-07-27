"""
Django EventStream 기반 통합 스트리밍 API

POST 요청 한 번으로 작업 시작 + SSE 실시간 알림 + 완료 데이터 수신
- 프론트엔드 API 호출 횟수 절반으로 감소
- 기존 /async + EventStream GET 방식도 유지
- django-eventstream send_event() 활용
"""

import logging
import base64
import uuid
from django.http import JsonResponse
from django.core.cache import caches
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from django_eventstream import send_event
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Book
from .serializers import BookPdfUploadSerializer
from characters.models import Character

logger = logging.getLogger(__name__)


class BookPdfUploadStreamView(APIView):
    """
    책 PDF 업로드 + 실시간 처리 상태 스트리밍 통합 API
    POST 요청 한 번으로 업로드 시작 + SSE 채널 연결 + 완료 시 결과 수신
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="""PDF 파일을 업로드하고 실시간 처리 상태를 스트리밍으로 받습니다. (JWT 인증 필요)
        
        통합 처리 방식:
        1. POST 요청으로 PDF 업로드 및 작업 시작
        2. 즉시 SSE 채널 정보 응답 (book_id, channel)
        3. 프론트엔드는 응답의 eventstream_url로 SSE 연결
        4. 백그라운드 처리 진행상황 실시간 푸시
        5. 완료 시 최종 책 데이터 SSE로 전송
        
        SSE 이벤트 타입:
        - status: 처리 상태 업데이트 (PENDING, PROCESSING)
        - completed: 처리 완료 (완성된 책 데이터 포함)
        - error: 오류 발생
        
        장점:
        - API 호출 1번만 필요 (기존 2번 → 1번)
        - 실시간 진행상황 모니터링
        - 완료 시 즉시 결과 수신
        """,
        manual_parameters=[
            openapi.Parameter(
                'title',
                openapi.IN_FORM,
                description="책 제목",
                type=openapi.TYPE_STRING,
                required=True
            ),
            openapi.Parameter(
                'pdf',
                openapi.IN_FORM,
                description="PDF 파일",
                type=openapi.TYPE_FILE,
                required=True
            ),
        ],
        responses={
            202: openapi.Response(
                description="업로드 시작 및 SSE 채널 정보",
                examples={
                    "application/json": {
                        "book_id": 123,
                        "title": "업로드된 책",
                        "task_id": "abc-def-123",
                        "channel": "book-123",
                        "eventstream_url": "/events/?channel=book-123",
                        "message": "PDF 업로드 완료. 실시간 처리 상태는 EventStream으로 확인하세요.",
                        "sse_instructions": {
                            "connect_to": "/events/?channel=book-123",
                            "events": ["status", "completed", "error"],
                            "note": "처리 완료 시 'completed' 이벤트로 최종 책 데이터를 받습니다."
                        }
                    }
                }
            ),
            400: openapi.Response(description="잘못된 요청"),
            401: openapi.Response(description="인증 필요"),
            500: openapi.Response(description="서버 오류")
        },
        tags=['스트리밍 통합 API (신규)'],
        consumes=['multipart/form-data']
    )
    def post(self, request):
        print("📝 통합 스트리밍 PDF 업로드 요청 시작")
        print("👤 요청 사용자:", request.user.username if request.user.is_authenticated else "익명")

        serializer = BookPdfUploadSerializer(data=request.data)
        if not serializer.is_valid():
            print("❌ Serializer 검증 실패:", serializer.errors)
            return Response({
                "status": "error",
                "error_code": 400,
                "message": "입력 형식이 올바르지 않습니다.",
                "details": serializer.errors
            }, status=400)

        title = serializer.validated_data['title']
        pdf_file = serializer.validated_data['pdf']

        print(f"✅ 검증 완료 - 제목: {title}, 파일명: {pdf_file.name}")

        try:
            # 1. 즉시 Book 레코드 생성 (PENDING 상태)
            book = Book.objects.create(
                title=title,
                processing_status='PENDING'
            )
            print(f"📚 책 레코드 생성 완료 - ID: {book.id}")

            # 2. SSE 채널 즉시 초기화 (현재 상태 전송)
            channel = f'book-{book.id}'
            send_event(channel, 'status', {
                'book_id': book.id,
                'title': book.title,
                'processing_status': 'PENDING',
                'message': 'PDF 업로드 완료. 처리를 시작합니다...',
                'timestamp': book.created_at.isoformat()
            })

            # 3. PDF 파일을 base64로 인코딩
            pdf_file.seek(0)
            pdf_content = pdf_file.read()
            pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
            
            # 4. Celery 태스크 시작
            from .tasks import process_book_pdf_task
            task = process_book_pdf_task.delay(
                book_id=book.id,
                pdf_file_content=pdf_base64,
                pdf_file_name=pdf_file.name
            )
            
            # 5. 태스크 ID 저장
            book.task_id = task.id
            book.save()
            
            print(f"🚀 비동기 처리 시작 - Task ID: {task.id}")

            # 6. 즉시 SSE 채널 정보 응답
            return Response({
                "book_id": book.id,
                "title": book.title,
                "task_id": task.id,
                "channel": channel,
                "eventstream_url": f"/events/?channel={channel}",
                "message": "PDF 업로드 완료. 실시간 처리 상태는 EventStream으로 확인하세요.",
                "sse_instructions": {
                    "connect_to": f"/events/?channel={channel}",
                    "events": ["status", "completed", "error"],
                    "note": "처리 완료 시 'completed' 이벤트로 최종 책 데이터를 받습니다."
                }
            }, status=202)  # 202 Accepted

        except Exception as e:
            print(f"[ERROR] 초기 처리 중 오류 발생: {str(e)}")
            import traceback
            print(f"[ERROR] 상세 스택 트레이스:\n{traceback.format_exc()}")

            return Response({
                "status": "error",
                "error_code": 500,
                "message": f"초기 처리 중 오류가 발생했습니다: {str(e)}"
            }, status=500)


class CharacterGenerateStreamView(APIView):
    """
    캐릭터 생성 + 실시간 처리 상태 스트리밍 통합 API
    POST 요청 한 번으로 생성 시작 + SSE 채널 연결 + 완료 시 결과 수신
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="""책의 캐릭터들을 생성하고 실시간 처리 상태를 스트리밍으로 받습니다. (JWT 인증 필요)
        
        조건부 처리:
        - 캐릭터가 이미 존재하면: 기존 캐릭터 목록 즉시 반환 (200)
        - 캐릭터가 없으면: 생성 시작 + SSE 스트리밍 (202)
        
        통합 처리 방식 (생성 시):
        1. POST 요청으로 캐릭터 생성 시작
        2. 즉시 SSE 채널 정보 응답 (book_id, channel)
        3. 프론트엔드는 응답의 eventstream_url로 SSE 연결
        4. 백그라운드 처리 단계별 진행상황 실시간 푸시
        5. 완료 시 최종 캐릭터 목록 SSE로 전송
        
        SSE 이벤트 타입:
        - status: 단계별 처리 상태 (pdf_chunking, character_extraction, scene_generation)
        - progress: 진행률 업데이트 (청크 처리, 캐릭터 생성 등)
        - completed: 처리 완료 (생성된 캐릭터 목록 포함)
        - error: 오류 발생
        """,
        responses={
            200: openapi.Response(
                description="기존 캐릭터 목록 반환",
                examples={
                    "application/json": {
                        "status": "existing",
                        "message": "이미 5개의 캐릭터가 존재합니다.",
                        "book_id": 1,
                        "book_title": "카라마조프가의 형제들",
                        "total_characters": 5,
                        "characters": "캐릭터 목록"
                    }
                }
            ),
            202: openapi.Response(
                description="캐릭터 생성 시작 및 SSE 채널 정보",
                examples={
                    "application/json": {
                        "status": "started",
                        "task_id": "abc-def-456",
                        "book_id": 1,
                        "book_title": "새로운 책",
                        "channel": "character-1",
                        "eventstream_url": "/events/?channel=character-1",
                        "message": "캐릭터 생성이 시작되었습니다.",
                        "sse_instructions": {
                            "connect_to": "/events/?channel=character-1",
                            "events": ["status", "progress", "completed", "error"],
                            "note": "처리 완료 시 'completed' 이벤트로 생성된 캐릭터 목록을 받습니다."
                        }
                    }
                }
            ),
            401: openapi.Response(description="인증 필요"),
            404: openapi.Response(description="책을 찾을 수 없음"),
            500: openapi.Response(description="서버 오류")
        },
        tags=['스트리밍 통합 API (신규)']
    )
    def post(self, request, book_id):
        print("🎭 통합 스트리밍 캐릭터 생성 요청 시작")
        print("👤 요청 사용자:", request.user.username if request.user.is_authenticated else "익명")
        
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'error': 'Book not found'}, status=404)

        # 🔄 조건부 생성: 기존 캐릭터 존재 여부 확인
        existing_characters = Character.objects.filter(book=book, is_deleted=False)
        if existing_characters.exists():
            print(f"✅ 기존 캐릭터 {existing_characters.count()}개 발견, 목록 반환")
            from characters.serializers import CharacterSimpleSerializer
            serializer = CharacterSimpleSerializer(existing_characters, many=True)
            return Response({
                "status": "existing",
                "message": f"이미 {existing_characters.count()}개의 캐릭터가 존재합니다.",
                "book_id": book_id,
                "book_title": book.title,
                "total_characters": existing_characters.count(),
                "characters": serializer.data
            }, status=200)

        print(f"✅ 검증 완료 - 책: {book.title}")

        try:
            # 1. SSE 채널 즉시 초기화
            channel = f'character-{book_id}'
            send_event(channel, 'status', {
                'book_id': book_id,
                'book_title': book.title,
                'status': 'PENDING',
                'step': 'initialization',
                'message': '캐릭터 생성을 시작합니다...',
                'progress_percentage': 0
            })

            # 2. Celery 태스크 시작
            from characters.tasks import generate_characters_task
            task = generate_characters_task.delay(book_id=book_id)
            
            print(f"🚀 비동기 처리 시작 - Task ID: {task.id}")

            # 3. 즉시 SSE 채널 정보 응답
            return Response({
                "status": "started",
                "task_id": task.id,
                "book_id": book_id,
                "book_title": book.title,
                "channel": channel,
                "eventstream_url": f"/events/?channel={channel}",
                "message": "캐릭터 생성이 시작되었습니다.",
                "sse_instructions": {
                    "connect_to": f"/events/?channel={channel}",
                    "events": ["status", "progress", "completed", "error"],
                    "note": "처리 완료 시 'completed' 이벤트로 생성된 캐릭터 목록을 받습니다."
                }
            }, status=202)  # 202 Accepted

        except Exception as e:
            print(f"[ERROR] 초기 처리 중 오류 발생: {str(e)}")
            import traceback
            print(f"[ERROR] 상세 스택 트레이스:\n{traceback.format_exc()}")

            return Response({
                'status': 'error',
                'error_code': 500,
                'message': f'초기 처리 중 오류가 발생했습니다: {str(e)}'
            }, status=500)


class ScriptGenerateStreamView(APIView):
    """
    대본 생성 + 실시간 처리 상태 스트리밍 통합 API
    POST 요청 한 번으로 생성 시작 + SSE 채널 연결 + 완료 시 결과 수신
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="""캐릭터의 대본을 생성하고 실시간 처리 상태를 스트리밍으로 받습니다. (JWT 인증 필요)
        
        통합 처리 방식:
        1. POST 요청으로 대본 생성 시작
        2. 즉시 script_id 생성 및 SSE 채널 정보 응답
        3. 프론트엔드는 응답의 eventstream_url로 SSE 연결
        4. 백그라운드 처리 진행상황 실시간 푸시
        5. 완료 시 최종 대본 데이터 SSE로 전송
        
        SSE 이벤트 타입:
        - status: 처리 상태 업데이트 (PROCESSING)
        - progress: 장면별 생성 진행상황
        - completed: 처리 완료 (생성된 대본 데이터 포함)
        - error: 오류 발생
        """,
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'scene_count': openapi.Schema(
                    type=openapi.TYPE_INTEGER,
                    description="생성할 장면 수 (기본값: 3)",
                    default=3
                )
            }
        ),
        responses={
            202: openapi.Response(
                description="대본 생성 시작 및 SSE 채널 정보",
                examples={
                    "application/json": {
                        "status": "started",
                        "task_id": "abc-def-789",
                        "script_id": "script-uuid-123",
                        "character_id": 456,
                        "character_name": "이반 카라마조프",
                        "channel": "script-script-uuid-123",
                        "eventstream_url": "/events/?channel=script-script-uuid-123",
                        "message": "대본 생성이 시작되었습니다.",
                        "sse_instructions": {
                            "connect_to": "/events/?channel=script-script-uuid-123",
                            "events": ["status", "progress", "completed", "error"],
                            "note": "처리 완료 시 'completed' 이벤트로 생성된 대본 데이터를 받습니다."
                        }
                    }
                }
            ),
            401: openapi.Response(description="인증 필요"),
            404: openapi.Response(description="캐릭터를 찾을 수 없음"),
            500: openapi.Response(description="서버 오류")
        },
        tags=['스트리밍 통합 API (신규)']
    )
    def post(self, request, character_id):
        print("📝 통합 스트리밍 대본 생성 요청 시작")
        print("👤 요청 사용자:", request.user.username if request.user.is_authenticated else "익명")
        
        try:
            character = Character.objects.get(id=character_id, is_deleted=False)
        except Character.DoesNotExist:
            return Response({'error': 'Character not found'}, status=404)

        # 장면 수 파라미터 (기본값: 3)
        scene_count = int(request.data.get('scene_count', 3))
        
        print(f"✅ 검증 완료 - 캐릭터: {character.characterName}, 장면 수: {scene_count}")

        try:
            # 1. script_id 미리 생성
            script_id = str(uuid.uuid4())
            
            # 2. SSE 채널 즉시 초기화
            channel = f'script-{script_id}'
            send_event(channel, 'status', {
                'script_id': script_id,
                'character_id': character_id,
                'character_name': character.characterName,
                'status': 'PENDING',
                'message': '대본 생성을 시작합니다...',
                'scene_count': scene_count
            })

            # 3. Celery 태스크 시작 (script_id 전달)
            from characters.tasks import generate_script_task
            task = generate_script_task.delay(
                character_id=character_id,
                scene_count=scene_count,
                script_id=script_id
            )
            
            print(f"🚀 비동기 처리 시작 - Task ID: {task.id}, Script ID: {script_id}")

            # 4. 즉시 SSE 채널 정보 응답
            return Response({
                "status": "started",
                "task_id": task.id,
                "script_id": script_id,
                "character_id": character_id,
                "character_name": character.characterName,
                "channel": channel,
                "eventstream_url": f"/events/?channel={channel}",
                "message": "대본 생성이 시작되었습니다.",
                "sse_instructions": {
                    "connect_to": f"/events/?channel={channel}",
                    "events": ["status", "progress", "completed", "error"],
                    "note": "처리 완료 시 'completed' 이벤트로 생성된 대본 데이터를 받습니다."
                }
            }, status=202)  # 202 Accepted

        except Exception as e:
            print(f"[ERROR] 초기 처리 중 오류 발생: {str(e)}")
            import traceback
            print(f"[ERROR] 상세 스택 트레이스:\n{traceback.format_exc()}")

            return Response({
                'status': 'error',
                'error_code': 500,
                'message': f'초기 처리 중 오류가 발생했습니다: {str(e)}'
            }, status=500) 