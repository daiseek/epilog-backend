from django_eventstream import send_event
import logging

logger = logging.getLogger(__name__)

def push_book_completed_event(task_id: str, s3_url: str):
    """
    책 처리 완료 이벤트 전송
    
    Args:
        task_id: 작업 ID
        s3_url: S3에 업로드된 PDF URL
    """
    channel = f"task_{task_id.replace('-', '_')}"
    logger.info(f"[push_book_completed_event] task_id={task_id}, s3_url={s3_url}")
    logger.info(f"[push_book_completed_event] 채널명: {channel}")
    
    try:
        print(f"[DEBUG] send_event 호출 직전 - 채널: {channel}")
        send_event(channel, "completed", {"s3_url": s3_url})
        print(f"[DEBUG] send_event 호출 성공 - 채널: {channel}")
        logger.info(f"[SSE] 책 처리 완료 이벤트 전송 성공: {task_id}")
    except Exception as e:
        print(f"[DEBUG] send_event 실패 - 채널: {channel}, 오류: {str(e)}")
        logger.error(f"[SSE ERROR] task={task_id}: {str(e)}")

def push_book_error_event(task_id: str, error_message: str):
    """
    책 처리 오류 이벤트 전송
    
    Args:
        task_id: 작업 ID  
        error_message: 오류 메시지
    """
    channel = f"task_{task_id.replace('-', '_')}"
    logger.info(f"[push_book_error_event] task_id={task_id}, error={error_message}")
    logger.info(f"[push_book_error_event] 채널명: {channel}")
    
    try:
        print(f"[DEBUG] send_event 호출 직전 - 채널: {channel}")
        send_event(channel, "error", {"error_message": error_message})
        print(f"[DEBUG] send_event 호출 성공 - 채널: {channel}")
        logger.info(f"[SSE] 책 처리 오류 이벤트 전송 성공: {task_id}")
    except Exception as e:
        print(f"[DEBUG] send_event 실패 - 채널: {channel}, 오류: {str(e)}")
        logger.error(f"[SSE ERROR] task={task_id}: {str(e)}") 