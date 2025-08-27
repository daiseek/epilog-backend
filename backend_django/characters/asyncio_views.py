"""Characters 앱 asyncio 기반 뷰"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Character
from books.models import Book
from .serializers import (
    CharacterAsyncResponseSerializer,
    CharacterErrorResponseSerializer,
    CharacterDetailedErrorResponseSerializer,
    ScriptAsyncResponseSerializer,
    CharacterSimpleSerializer
)


class CharacterGenerateAsyncioView(APIView):
    """캐릭터 생성 기능 (asyncio 비동기 버전)"""
    permission_classes = [IsAuthenticated]  # JWT 인증 필요
    
    @swagger_auto_schema(
        operation_description="""책의 캐릭터들을 asyncio로 비동기 생성합니다. (JWT 인증 필요)
        
        조건부 생성 로직:
        - 캐릭터가 이미 존재하면: 기존 캐릭터 목록 반환 (200)
        - 캐릭터가 없으면: 백그라운드에서 asyncio로 비동기 생성 (202)
        
        asyncio 처리 과정 (생성 시):
        1. 즉시 Task ID 반환
        2. 백그라운드에서 asyncio로 처리:
           - PDF 다운로드 및 청킹 (비동기)
           - 청크별 병렬 캐릭터 추출 (asyncio.gather 사용)
           - 중복 제거 및 스마트 병합
           - 캐릭터별 장면 생성을 병렬 실행
           - DB 저장 (비동기)
        
        Celery 대비 asyncio 장점:
        - I/O bound 작업의 효율적 병렬 처리
        - 메모리 사용량 최적화
        - 별도 브로커 불필요
        - 더 빠른 응답 시간
        
        가능한 오류:
        - 401: 인증 필요
        - 404: 책을 찾을 수 없음
        - 500: 초기 처리 실패
        """,
        responses={
            200: openapi.Response(
                description="기존 캐릭터 목록 반환",
                examples={
                    "application/json": {
                        "message": "이미 5개의 캐릭터가 존재합니다.",
                        "book_id": 1,
                        "book_title": "카라마조프가의 형제들",
                        "total_characters": 5,
                        "characters": "캐릭터 목록"
                    }
                }
            ),
            202: CharacterAsyncResponseSerializer,
            401: openapi.Response(description="인증 필요"),
            404: CharacterErrorResponseSerializer,
            500: CharacterDetailedErrorResponseSerializer
        },
        tags=['캐릭터 관리 (AsyncIO)']
    )
    def post(self, request, book_id):
        print("🎭 AsyncIO 캐릭터 생성 요청 시작")
        print("👤 요청 사용자:", request.user.username if request.user.is_authenticated else "익명")
        
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'error': 'Book not found'}, status=404)

        # 조건부 생성: 기존 캐릭터 존재 여부 확인
        existing_characters = Character.objects.filter(book=book, is_deleted=False)
        if existing_characters.exists():
            print(f"✅ 기존 캐릭터 {existing_characters.count()}개 발견, 목록 반환")
            serializer = CharacterSimpleSerializer(existing_characters, many=True)
            return Response({
                "message": f"이미 {existing_characters.count()}개의 캐릭터가 존재합니다.",
                "book_id": book_id,
                "book_title": book.title,
                "total_characters": existing_characters.count(),
                "characters": serializer.data
            }, status=200)

        print(f"✅ 검증 완료 - 책: {book.title}")

        try:
            # asyncio 태스크 시작
            import asyncio
            import threading
            from .asyncio_tasks import character_processor
            
            # 백그라운드 스레드에서 asyncio 실행
            def run_async_task():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        character_processor.generate_characters_async(book_id)
                    )
                    print(f"✅ AsyncIO 캐릭터 생성 완료: {result}")
                    loop.close()
                except Exception as e:
                    print(f"[ERROR] AsyncIO 캐릭터 생성 백그라운드 실행 오류: {str(e)}")
            
            # 백그라운드 스레드 시작
            thread = threading.Thread(target=run_async_task, daemon=True)
            thread.start()
            
            task_id = f"asyncio-char-{book_id}"
            print(f"🚀 AsyncIO 캐릭터 생성 시작 - Task ID: {task_id}")

            # 즉시 응답 반환
            return Response({
                "task_id": task_id,
                "book_id": book_id,
                "book_title": book.title,
                "processing_type": "asyncio",
                "message": "AsyncIO로 캐릭터 생성이 시작되었습니다. SSE 연결을 통해 진행 상황을 확인할 수 있습니다.",
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


class ScriptGenerateAsyncioView(APIView):
    """대본 생성 기능 (asyncio 비동기 버전)"""
    permission_classes = [IsAuthenticated]  # JWT 인증 필요
    
    @swagger_auto_schema(
        operation_description="""캐릭터의 대본을 asyncio로 비동기 생성합니다. (JWT 인증 필요)
        
        처리 과정:
        1. 즉시 Script ID 및 Task ID 반환
        2. 백그라운드에서 asyncio로 대본 처리:
           - 캐릭터 정보 조회 (비동기)
           - 조연 캐릭터 정보 수집 (비동기)
           - Gemini API로 대본 생성 (별도 스레드)
           - Redis에 대본 캐싱 (비동기)
        
        Celery 대비 asyncio 장점:
        - I/O bound 작업의 효율적 처리
        - 빠른 응답 시간
        - 리소스 효율성
        
        가능한 오류:
        - 401: 인증 필요
        - 404: 캐릭터를 찾을 수 없음
        - 500: 초기 처리 실패
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
            202: ScriptAsyncResponseSerializer,
            401: openapi.Response(description="인증 필요"),
            404: CharacterErrorResponseSerializer,
            500: CharacterDetailedErrorResponseSerializer
        },
        tags=['대본 생성 (AsyncIO)']
    )
    def post(self, request, character_id):
        print("📝 AsyncIO 대본 생성 요청 시작")
        print("👤 요청 사용자:", request.user.username if request.user.is_authenticated else "익명")
        
        try:
            character = Character.objects.get(id=character_id, is_deleted=False)
        except Character.DoesNotExist:
            return Response({'error': 'Character not found'}, status=404)

        # 장면 수 파라미터 (기본값: 3)
        scene_count = int(request.data.get('scene_count', 3))
        
        print(f"✅ 검증 완료 - 캐릭터: {character.characterName}, 장면 수: {scene_count}")

        try:
            # script_id 미리 생성
            import uuid
            script_id = str(uuid.uuid4())
            
            # asyncio 태스크 시작
            import asyncio
            import threading
            from .asyncio_tasks import character_processor
            
            # 백그라운드 스레드에서 asyncio 실행
            def run_async_task():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        character_processor.generate_script_async(
                            character_id, scene_count, script_id
                        )
                    )
                    print(f"✅ AsyncIO 대본 생성 완료: {result}")
                    loop.close()
                except Exception as e:
                    print(f"[ERROR] AsyncIO 대본 생성 백그라운드 실행 오류: {str(e)}")
            
            # 백그라운드 스레드 시작
            thread = threading.Thread(target=run_async_task, daemon=True)
            thread.start()
            
            task_id = f"asyncio-script-{character_id}"
            print(f"🚀 AsyncIO 대본 생성 시작 - Task ID: {task_id}, Script ID: {script_id}")

            # 즉시 응답 반환 (script_id 포함)
            return Response({
                "task_id": task_id,
                "script_id": script_id,
                "character_id": character_id,
                "character_name": character.characterName,
                "processing_type": "asyncio",
                "message": f"AsyncIO로 대본 생성이 시작되었습니다. Script ID: {script_id} (영상 생성에 사용 가능)"
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
