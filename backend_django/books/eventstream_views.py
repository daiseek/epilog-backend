"""
Django EventStream 기반 SSE 구현

기존 자체 구현(580줄) → EventStream(간단한 구조)로 전환
- 실시간 Push 알림 (폴링 제거)
- 자동 연결 관리
- Redis Pub/Sub 최적화
"""

import logging
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django_eventstream import send_event
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@swagger_auto_schema(
    operation_description="""책 PDF 처리 상태를 실시간으로 받습니다. (EventStream 방식)
    
    EventStream 장점:
    - 즉시 Push 알림 (폴링 없음)
    - 자동 연결 관리
    - Redis Pub/Sub 최적화
    - 메모리 효율적
    
    사용법:
    1. 이 API로 채널 연결
    2. EventSource로 /events/?channel=book-{book_id} 접속
    3. 실시간 알림 수신
    
    이벤트 타입:
    - status: 상태 업데이트
    - completed: 처리 완료
    - error: 오류 발생
    """,
    responses={
        200: openapi.Response(description="채널 연결 성공"),
        404: openapi.Response(description="책을 찾을 수 없음"),
        401: openapi.Response(description="인증 필요")
    },
    tags=['EventStream SSE (신규)']
)
def book_processing_eventstream(request, book_id):
    """책 처리 상태를 EventStream으로 모니터링 시작"""
    try:
        from .models import Book
        book = Book.objects.get(id=book_id, is_deleted=False)
        
        # 즉시 현재 상태 전송
        send_event(f'book-{book_id}', 'status', {
            'book_id': book.id,
            'title': book.title,
            'processing_status': book.processing_status,
            'content': book.content,
            'pdf_url': book.pdf_url,
            'error_message': book.error_message,
            'timestamp': book.updated_at.isoformat() if book.updated_at else None
        })
        
        return JsonResponse({
            'message': f'책 "{book.title}" 실시간 모니터링 시작',
            'channel': f'book-{book_id}',
            'eventstream_url': f'/events/?channel=book-{book_id}',
            'current_status': book.processing_status
        })
        
    except Book.DoesNotExist:
        return JsonResponse({
            'error': f'책 ID {book_id}를 찾을 수 없습니다.'
        }, status=404)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@swagger_auto_schema(
    operation_description="""캐릭터 생성 상태를 실시간으로 받습니다. (EventStream 방식)
    
    book_id로 활성 캐릭터 생성 작업을 찾아 실시간 모니터링합니다.
    
    EventStream 개선사항:
    - 진행률 실시간 업데이트
    - 단계별 상세 정보
    - 자동 완료 감지
    
    사용법:
    1. 이 API로 채널 연결
    2. EventSource로 /events/?channel=character-{book_id} 접속
    3. 단계별 진행 상황 실시간 수신
    """,
    responses={
        200: openapi.Response(description="채널 연결 성공"),
        404: openapi.Response(description="활성 작업 없음"),
        401: openapi.Response(description="인증 필요")
    },
    tags=['EventStream SSE (신규)']
)
def character_generation_eventstream(request, book_id):
    """캐릭터 생성 상태를 EventStream으로 모니터링 시작"""
    try:
        from django.core.cache import caches
        from django_redis import get_redis_connection
        
        script_cache = caches['script_cache']
        redis_client = get_redis_connection("script_cache")
        
        # 활성 캐릭터 작업 찾기
        active_task = None
        pattern = f"*:character_task:*"
        
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            if ':character_task:' in key_str:
                task_id = key_str.split(':character_task:')[-1]
                task_data = script_cache.get(f'character_task:{task_id}')
                
                if (task_data and 
                    task_data.get('book_id') == book_id and 
                    task_data.get('status') in ['PENDING', 'PROCESSING']):
                    active_task = {'task_id': task_id, 'data': task_data}
                    break
        
        if not active_task:
            return JsonResponse({
                'error': f'책 ID {book_id}에 대한 활성 캐릭터 생성 작업을 찾을 수 없습니다.'
            }, status=404)
        
        # 즉시 현재 상태 전송
        task_data = active_task['data']
        send_event(f'character-{book_id}', 'status', {
            'task_id': active_task['task_id'],
            'book_id': book_id,
            'book_title': task_data.get('book_title'),
            'status': task_data.get('status'),
            'step': task_data.get('step'),
            'message': task_data.get('message'),
            'progress_percentage': calculate_progress(task_data),
            'total_chunks': task_data.get('total_chunks'),
            'processed_chunks': task_data.get('processed_chunks'),
            'total_characters': task_data.get('total_characters'),
            'processed_characters': task_data.get('processed_characters')
        })
        
        return JsonResponse({
            'message': f'캐릭터 생성 실시간 모니터링 시작',
            'channel': f'character-{book_id}',
            'eventstream_url': f'/events/?channel=character-{book_id}',
            'task_id': active_task['task_id'],
            'current_status': task_data.get('status')
        })
        
    except Exception as e:
        logger.error(f'캐릭터 생성 EventStream 오류: {str(e)}')
        return JsonResponse({
            'error': f'캐릭터 생성 모니터링 시작 실패: {str(e)}'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@swagger_auto_schema(
    operation_description="""대본 생성 상태를 실시간으로 받습니다. (EventStream 방식)
    
    character_id로 활성 대본 생성 작업을 찾아 실시간 모니터링합니다.
    
    EventStream 특징:
    - 즉시 상태 전송
    - 완료 시 대본 내용 포함
    - 자동 에러 감지
    """,
    responses={
        200: openapi.Response(description="채널 연결 성공"),
        404: openapi.Response(description="활성 작업 없음"),
        401: openapi.Response(description="인증 필요")
    },
    tags=['EventStream SSE (신규)']
)
def script_generation_eventstream(request, character_id):
    """대본 생성 상태를 EventStream으로 모니터링 시작"""
    try:
        from django.core.cache import caches
        from django_redis import get_redis_connection
        
        script_cache = caches['script_cache']
        redis_client = get_redis_connection("script_cache")
        
        # 활성 대본 작업 찾기
        active_task = None
        pattern = f"*:task:*"
        
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            if ':task:' in key_str:
                task_id = key_str.split(':task:')[-1]
                task_data = script_cache.get(f'task:{task_id}')
                
                if (task_data and 
                    task_data.get('character_id') == character_id and 
                    task_data.get('status') in ['PENDING', 'PROCESSING']):
                    active_task = {'task_id': task_id, 'data': task_data}
                    break
        
        if not active_task:
            return JsonResponse({
                'error': f'캐릭터 ID {character_id}에 대한 활성 대본 생성 작업을 찾을 수 없습니다.'
            }, status=404)
        
        # 즉시 현재 상태 전송
        task_data = active_task['data']
        send_event(f'script-{character_id}', 'status', {
            'task_id': active_task['task_id'],
            'character_id': character_id,
            'character_name': task_data.get('character_name'),
            'status': task_data.get('status'),
            'script_id': task_data.get('script_id'),
            'scene_count': task_data.get('scene_count'),
            'message': task_data.get('message'),
            'started_at': task_data.get('started_at'),
            'error_message': task_data.get('error_message')
        })
        
        return JsonResponse({
            'message': f'대본 생성 실시간 모니터링 시작',
            'channel': f'script-{character_id}',
            'eventstream_url': f'/events/?channel=script-{character_id}',
            'task_id': active_task['task_id'],
            'current_status': task_data.get('status')
        })
        
    except Exception as e:
        logger.error(f'대본 생성 EventStream 오류: {str(e)}')
        return JsonResponse({
            'error': f'대본 생성 모니터링 시작 실패: {str(e)}'
        }, status=500)


def calculate_progress(task_data):
    """진행률 계산 (0-100%)"""
    if task_data.get('step') == 'pdf_chunking':
        return 10
    elif task_data.get('step') == 'character_extraction':
        total = task_data.get('total_chunks', 1)
        processed = task_data.get('processed_chunks', 0)
        return 10 + (processed / total) * 50  # 10-60%
    elif task_data.get('step') == 'scene_generation':
        total = task_data.get('total_characters', 1)
        processed = task_data.get('processed_characters', 0)
        return 60 + (processed / total) * 35  # 60-95%
    elif task_data.get('step') == 'saving':
        return 95
    elif task_data.get('status') == 'COMPLETED':
        return 100
    return 0


# ========================
# 이벤트 발송 헬퍼 함수들
# ========================

def notify_book_progress(book_id, status, **extra_data):
    """책 처리 진행 상황 실시간 알림"""
    event_data = {
        'book_id': book_id,
        'status': status,
        'timestamp': extra_data.get('timestamp'),
        **extra_data
    }
    
    send_event(f'book-{book_id}', 'status', event_data)
    logger.info(f'📡 책 {book_id} 상태 알림: {status}')


def notify_character_progress(book_id, task_id, step, progress_data):
    """캐릭터 생성 진행 상황 실시간 알림"""
    event_data = {
        'task_id': task_id,
        'book_id': book_id,
        'step': step,
        'progress_percentage': calculate_progress(progress_data),
        **progress_data
    }
    
    send_event(f'character-{book_id}', 'progress', event_data)
    logger.info(f'📡 캐릭터 생성 {task_id} 진행: {step}')


def notify_character_completed(book_id, task_id, characters):
    """캐릭터 생성 완료 알림"""
    event_data = {
        'task_id': task_id,
        'book_id': book_id,
        'status': 'COMPLETED',
        'progress_percentage': 100,
        'characters': characters,
        'message': '캐릭터 생성이 완료되었습니다!'
    }
    
    send_event(f'character-{book_id}', 'completed', event_data)
    logger.info(f'🎉 캐릭터 생성 완료: {task_id}')


def notify_script_progress(character_id, task_id, status, **extra_data):
    """대본 생성 진행 상황 실시간 알림"""
    event_data = {
        'task_id': task_id,
        'character_id': character_id,
        'status': status,
        **extra_data
    }
    
    send_event(f'script-{character_id}', 'progress', event_data)
    logger.info(f'📡 대본 생성 {task_id} 상태: {status}')


def notify_script_completed(character_id, task_id, script_data):
    """대본 생성 완료 알림 (Redis 대본 데이터 포함)"""
    from django.core.cache import caches
    
    # 추가 Redis 데이터 조회 (혹시 놓친 데이터가 있을 경우)
    script_cache = caches['script_cache']
    script_id = script_data.get('script_id')
    
    # Redis에서 대본 데이터 재조회
    if script_id:
        redis_script_key = f"script:{script_id}"
        redis_script_data = script_cache.get(redis_script_key)
        
        if redis_script_data:
            script_data['full_redis_scenes'] = redis_script_data.get('scenes', [])
            script_data['redis_character_id'] = redis_script_data.get('characterId')
    
    event_data = {
        'task_id': task_id,
        'character_id': character_id,
        'status': 'COMPLETED',
        'script_data': script_data,
        'timestamp': script_data.get('completed_at', ''),
        'message': f'대본 생성이 완료되었습니다! (장면 수: {script_data.get("scene_count", 0)}개)'
    }
    
    send_event(f'script-{character_id}', 'completed', event_data)
    logger.info(f'🎉 대본 생성 완료: {task_id} - 장면 수: {script_data.get("scene_count", 0)}') 