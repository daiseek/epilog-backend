from django_eventstream import send_event
from django.core.cache import caches
import datetime
import logging
import traceback

logger = logging.getLogger(__name__)

def push_event(task_id: str, event_type: str, payload: dict):
    """
    단일 SSE 이벤트 전송 함수
    Django EventStream을 이용하여 이벤트 전송 함수를 커스텀

    Args:
        task_id: 고유한 작업 ID (ex. Celery task_id or script_id)
        event_type: 이벤트 유형 ('progress', 'completed', 'error' 등)
        payload: 클라이언트로 보낼 JSON 데이터
    """
    logger.info(f"📡 [push_event] task_id={task_id}, event_type={event_type}, payload={payload}")

    cache = caches['default']
    channel = f"task-{task_id}"
    now = datetime.datetime.now().isoformat()

    # Redis에 상태 기록 (progress/completed/error)
    state = {
        'progress': lambda: {**payload, 'status': 'PROCESSING', 'last_updated': now},
        'completed': lambda: {**payload, 'status': 'COMPLETED', 'completed_at': now, 'progress': 100},
        'error': lambda: {**payload, 'status': 'ERROR', 'failed_at': now}
    }.get(event_type, lambda: {**payload, 'status': 'UNKNOWN'})()

    cache.set(f"task_detail:{task_id}", state, timeout=3600)

    # SSE 전송 (오류가 발생해도 작업은 계속 진행)
    try:
        send_event(channel, event_type, {
            'task_id': task_id,
            'timestamp': now,
            **payload
        })
        logger.info(f"📡 [SSE] task={task_id} event={event_type}: {payload.get('message') or '...'}")
    except Exception as e:
        logger.error(f"❌ [SSE ERROR] task={task_id} event={event_type}: {str(e)}")
        logger.error(f"❌ [SSE TRACEBACK] {traceback.format_exc()}")
        # SSE 전송 실패해도 작업은 계속 진행 


# def test_send_event(task_id: str = "test123"):
#     """
#     테스트용 이벤트 전송 함수
#     """
#     push_event(task_id, "progress", {"message": "작업 시작됨", "progress": 25})
#     push_event(task_id, "progress", {"message": "작업 진행 중", "progress": 75})
#     push_event(task_id, "completed", {"message": "작업 완료!", "result": "성공"}) 