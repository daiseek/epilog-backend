from celery import shared_task
from celery.utils.log import get_task_logger
from django.core.cache import caches
from .models import Character
from .gemini_client import (
    generate_scenes_with_gemini,
    parse_scene_list
)
import datetime

# Celery 전용 로거 설정
logger = get_task_logger(__name__)

@shared_task(bind=True)
def generate_script_task(self, character_id, scene_count=3):
    """
    대본을 비동기적으로 생성하는 Celery 태스크 (Redis 기반)
    
    Args:
        character_id: Character 인스턴스 ID
        scene_count: 생성할 장면 수
    """
    task_id = self.request.id
    script_cache = caches['script_cache']
    
    # Redis에 태스크 상태 저장
    task_key = f"task:{task_id}"
    
    try:
        # 1. 초기 상태 저장
        script_cache.set(task_key, {
            "status": "PROCESSING",
            "character_id": character_id,
            "scene_count": scene_count,
            "started_at": datetime.datetime.now().isoformat(),
            "message": "대본 생성 중..."
        }, timeout=3600)  # 1시간
        
        logger.info(f"📝 [TASK START] 대본 생성 시작 - Character ID: {character_id}, Task ID: {task_id}")
        
        # Character 조회
        character = Character.objects.get(id=character_id, is_deleted=False)
        logger.info(f"🎭 [CHARACTER] 캐릭터 정보 로드 - 이름: '{character.characterName}', 주인공: {character.isMain}")
        
        # 조연 캐릭터 정보 수집
        sub_characters = Character.objects.filter(
            book=character.book, isMain=False, is_deleted=False
        ).exclude(id=character.id)
        logger.info(f"👥 [SUB CHARACTERS] 조연 캐릭터 {sub_characters.count()}명 수집")
        
        # 2. Gemini API로 대본 생성
        logger.info("🤖 [STEP 1/2] Gemini API 대본 생성 시작...")
        
        # 진행 상태 업데이트
        script_cache.set(task_key, {
            "status": "PROCESSING",
            "character_id": character_id,
            "character_name": character.characterName,
            "scene_count": scene_count,
            "started_at": datetime.datetime.now().isoformat(),
            "message": "Gemini API로 대본 생성 중..."
        }, timeout=3600)
        
        raw_text = generate_scenes_with_gemini(
            main_character=character,
            sub_characters=sub_characters,
            scene_count=scene_count,
        )
        logger.info(f"📄 [STEP 1/2] Gemini API 응답 완료 - 응답 길이: {len(raw_text)} 문자")
        
        # 3. 파싱 및 Redis 캐시 저장
        logger.info("📋 [STEP 2/2] 대본 파싱 및 캐싱 시작...")
        
        # 진행 상태 업데이트
        script_cache.set(task_key, {
            "status": "PROCESSING",
            "character_id": character_id,
            "character_name": character.characterName,
            "scene_count": scene_count,
            "started_at": datetime.datetime.now().isoformat(),
            "message": "대본 파싱 및 저장 중..."
        }, timeout=3600)
        
        parsed_result = parse_scene_list(raw_text)
        
        script_id = parsed_result.get("script_id")
        scene_texts = parsed_result.get("scenes", [])
        logger.info(f"🔍 [PARSING] 파싱 완료 - Script ID: {script_id}, 장면 수: {len(scene_texts)}")
        
        # scene 구조 생성
        generated_scenes = []
        for scene in scene_texts:
            scene_id = scene.get("sceneId")
            generated_scenes.append({
                "sceneId": scene_id,
                "background": scene.get("background"),
                "mood": scene.get("mood"),
                "style": scene.get("style"),
                "camera": scene.get("camera"),
                "soundtrack": scene.get("soundtrack"),
                "characters": scene.get("characters"),
                "rewriting_prompt": scene.get("rewriting_prompt"),
                "rewriting_id": scene.get("rewriting_id")
            })
        
        # 대본을 Redis에 저장
        script_cache_key = f"script:{script_id}"
        script_cache.set(script_cache_key, {
            "characterId": character_id,
            "scenes": generated_scenes
        }, timeout=2000)  # 2000초 동안 캐시
        logger.info(f"💾 [CACHE] Redis 대본 캐싱 완료 - Key: {script_cache_key}")
        
        # 4. 완료 상태 저장
        script_cache.set(task_key, {
            "status": "COMPLETED",
            "character_id": character_id,
            "character_name": character.characterName,
            "scene_count": scene_count,
            "script_id": script_id,
            "started_at": datetime.datetime.now().isoformat(),
            "completed_at": datetime.datetime.now().isoformat(),
            "message": "대본 생성이 완료되었습니다."
        }, timeout=3600)
        
        logger.info(f"✅ [TASK COMPLETE] 대본 생성 완료 - Task ID: {task_id}, Script ID: {script_id}")
        
        return {
            "status": "success",
            "task_id": task_id,
            "character_id": character_id,
            "script_id": script_id,
            "scene_count": len(generated_scenes)
        }
        
    except Character.DoesNotExist:
        error_msg = f"캐릭터를 찾을 수 없습니다 - ID: {character_id}"
        logger.error(f"❌ [ERROR] {error_msg}")
        
        # 실패 상태 저장
        script_cache.set(task_key, {
            "status": "FAILED",
            "character_id": character_id,
            "scene_count": scene_count,
            "started_at": datetime.datetime.now().isoformat(),
            "failed_at": datetime.datetime.now().isoformat(),
            "error_message": error_msg
        }, timeout=3600)
        
        return {"status": "error", "message": error_msg}
    
    except Exception as e:
        error_msg = f"대본 생성 중 오류 발생: {str(e)}"
        logger.error(f"❌ [ERROR] {error_msg}")
        logger.error(f"❌ [ERROR] 오류 타입: {type(e).__name__}")
        
        # 실패 상태 저장
        script_cache.set(task_key, {
            "status": "FAILED",
            "character_id": character_id,
            "scene_count": scene_count,
            "started_at": datetime.datetime.now().isoformat(),
            "failed_at": datetime.datetime.now().isoformat(),
            "error_message": error_msg
        }, timeout=3600)
        
        import traceback
        logger.error(f"❌ [ERROR] 상세 스택 트레이스:\n{traceback.format_exc()}")
        
        # Celery에 실패 상태 전달
        self.update_state(
            state='FAILURE',
            meta={'error': error_msg, 'task_id': task_id}
        )
        raise Exception(error_msg) 