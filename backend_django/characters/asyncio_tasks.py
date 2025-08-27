"""Characters 앱 asyncio 기반 비동기 작업"""

import asyncio
import aioredis
import json
import uuid
from datetime import datetime
from django.core.cache import caches
from asgiref.sync import sync_to_async
from .models import Character, CharacterScene
from .gemini_client import (
    generate_scenes_with_gemini,
    parse_scene_list,
    fetch_pdf_from_s3,
    extract_characters_from_chunk_with_retry,
    merge_and_deduplicate_characters,
    create_character_scenes_with_retry
)
from .pdf_chunker import (
    chunk_pdf_content,
    smart_chunk_sizing,
    prioritize_character_chunks
)
from books.models import Book


class AsyncCharacterProcessor:
    """asyncio 기반 캐릭터 처리 클래스"""
    
    def __init__(self):
        self.redis_url = "redis://backend-redis:6379/3"
    
    async def send_character_task_event(self, task_id: str, event_type: str, data: dict):
        """
        Redis pub/sub을 통한 비동기 이벤트 전송 (characters 도메인용)
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
            print(f"[DEBUG] AsyncIO Characters Redis 이벤트 전송 성공 - 채널: {channel}, 타입: {event_type}")
            return True
        except Exception as e:
            print(f"[DEBUG] AsyncIO Characters Redis 이벤트 전송 실패 - 채널: {channel}, 오류: {str(e)}")
            return False
    
    async def extract_characters_from_chunk_async(self, chunk):
        """
        하나의 PDF 청크에서 캐릭터를 비동기 추출
        """
        chunk_number = chunk.get('chunk_number', 'N/A')
        
        try:
            print(f"🤖 청크 {chunk_number} 비동기 처리 시작...")
            
            # CPU bound 작업을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            chunk_characters = await loop.run_in_executor(
                None, 
                extract_characters_from_chunk_with_retry,
                chunk['text'],
                chunk
            )
            
            print(f"✅ 청크 {chunk_number} 처리 완료 - {len(chunk_characters)}명 발견")
            return chunk_characters
            
        except Exception as e:
            print(f"❌ 청크 {chunk_number} 처리 중 오류 발생: {str(e)}")
            raise
    
    async def create_character_with_scenes_async(self, char_data, book_id, task_id, char_index, total_chars):
        """
        하나의 캐릭터에 대해 DB 생성 + 장면 생성을 비동기 수행
        """
        char_name = char_data.get('characterName', 'Unknown')
        
        try:
            print(f"🎭 캐릭터 '{char_name}' 비동기 생성 시작... ({char_index+1}/{total_chars})")
            
            # 1. Book 조회 (비동기)
            book = await sync_to_async(Book.objects.get)(id=book_id)
            
            # 2. Character DB 생성 (비동기)
            character = await sync_to_async(Character.objects.create)(
                characterName=char_data['characterName'],
                isMain=char_data['isMain'],
                age=char_data['age'],
                gender=char_data['gender'],
                characterDescription=char_data['characterDescription'],
                book=book
            )
            
            # 3. Gemini API로 장면 생성 (CPU bound 작업을 별도 스레드에서)
            loop = asyncio.get_event_loop()
            scenes = await loop.run_in_executor(
                None,
                create_character_scenes_with_retry,
                char_data,
                book.content
            )
            
            scene_data = []
            
            # 4. CharacterScene DB 생성 (비동기)
            for scene_info in scenes:
                scene = await sync_to_async(CharacterScene.objects.create)(
                    character=character,
                    scene_content=scene_info.get('scene_content', ''),
                    start_page=scene_info.get('start_page', 1),
                    finish_page=scene_info.get('finish_page', 10)
                )
                scene_data.append({
                    'id': scene.id,
                    'scene_content': scene.scene_content,
                    'start_page': scene.start_page,
                    'finish_page': scene.finish_page,
                })
            
            # 5. 결과 반환
            character_result = {
                'id': character.id,
                'characterName': character.characterName,
                'isMain': character.isMain,
                'age': character.age,
                'gender': character.gender,
                'characterDescription': character.characterDescription,
                'scenes': scene_data
            }
            
            print(f"✅ 캐릭터 '{char_name}' 생성 완료 - {len(scene_data)}개 장면")
            return character_result
            
        except Exception as e:
            print(f"❌ 캐릭터 '{char_name}' 생성 실패: {str(e)}")
            raise
    
    async def generate_characters_async(self, book_id: int):
        """
        asyncio를 사용한 캐릭터 생성 전체 워크플로우
        """
        task_id = str(uuid.uuid4())
        script_cache = caches['script_cache']
        task_key = f"character_task:{task_id}"
        
        try:
            # 1. 초기 상태 저장 및 이벤트 전송
            init_data = {
                "status": "PROCESSING", 
                "book_id": book_id, 
                "step": "initialization", 
                "message": "캐릭터 생성 초기화 중..."
            }
            await sync_to_async(script_cache.set)(task_key, init_data, timeout=7200)
            
            book = await sync_to_async(Book.objects.get)(id=book_id)
            await self.send_character_task_event(task_id, "started", {
                "message": "캐릭터 생성 시작됨", 
                "book_id": book_id, 
                "book_title": book.title
            })
            
            # 2. PDF 다운로드 및 청킹
            await self.send_character_task_event(task_id, "progress", {
                "message": "PDF 다운로드 및 청킹 중...", 
                "step": "pdf_processing", 
                "book_title": book.title
            })
            
            # CPU bound 작업을 별도 스레드에서 실행
            loop = asyncio.get_event_loop()
            pdf_content = await loop.run_in_executor(None, fetch_pdf_from_s3, book_id)
            optimal_chunk_size = await loop.run_in_executor(None, smart_chunk_sizing, len(pdf_content))
            chunks = await loop.run_in_executor(None, chunk_pdf_content, pdf_content, f"book_{book_id}.pdf", optimal_chunk_size)
            prioritized_chunks = await loop.run_in_executor(None, prioritize_character_chunks, chunks)
            
            max_chunks = 8 if len(prioritized_chunks) > 8 else len(prioritized_chunks)
            selected_chunks = prioritized_chunks[:max_chunks]
            
            print(f"📊 [CHUNKING] 청킹 완료 - 총 {len(chunks)}개 중 상위 {len(selected_chunks)}개 선택")
            
            # 3. 청크별 캐릭터 추출을 병렬 실행
            await self.send_character_task_event(task_id, "progress", {
                "message": f"병렬 캐릭터 추출 시작...", 
                "step": "character_extraction"
            })
            
            # 모든 청크를 병렬로 처리
            chunk_tasks = [
                self.extract_characters_from_chunk_async(chunk) 
                for chunk in selected_chunks
            ]
            all_chunk_characters_list = await asyncio.gather(*chunk_tasks, return_exceptions=True)
            
            # 예외 처리된 결과 필터링
            valid_results = [
                result for result in all_chunk_characters_list 
                if not isinstance(result, Exception)
            ]
            
            # 4. 캐릭터 병합 및 중복 제거
            await sync_to_async(script_cache.set)(task_key, {
                "status": "PROCESSING", 
                "book_id": book_id, 
                "step": "character_merging",
                "message": "캐릭터 병합 및 중복 제거 중..."
            }, timeout=7200)
            
            await self.send_character_task_event(task_id, "progress", {
                "message": "캐릭터 병합 및 중복 제거 중...", 
                "step": "character_merging"
            })
            
            final_characters = await loop.run_in_executor(
                None, 
                merge_and_deduplicate_characters, 
                valid_results
            )
            
            if not final_characters:
                raise Exception("캐릭터 추출 실패: 유효한 캐릭터가 발견되지 않았습니다.")
            
            # 5. 캐릭터 수 제한
            if len(final_characters) > 10:
                final_characters = final_characters[:10]
            
            print(f"✅ 최종 선택된 캐릭터 수: {len(final_characters)}명")
            
            # 6. 캐릭터별 장면 생성을 병렬 실행
            await sync_to_async(script_cache.set)(task_key, {
                "status": "PROCESSING", 
                "book_id": book_id, 
                "step": "parallel_scene_generation",
                "total_characters": len(final_characters), 
                "processed_characters": 0,
                "message": f"병렬 장면 생성 시작... (0/{len(final_characters)})"
            }, timeout=7200)
            
            await self.send_character_task_event(task_id, "progress", {
                "message": f"병렬 장면 생성 시작...", 
                "step": "parallel_scene_generation"
            })
            
            # 모든 캐릭터를 병렬로 처리
            character_tasks = [
                self.create_character_with_scenes_async(char_data, book_id, task_id, i, len(final_characters))
                for i, char_data in enumerate(final_characters)
            ]
            all_character_results = await asyncio.gather(*character_tasks, return_exceptions=True)
            
            # 성공한 결과만 필터링
            successful_characters = [
                result for result in all_character_results 
                if not isinstance(result, Exception)
            ]
            
            # 7. 완료 상태 저장 및 이벤트 전송
            completed_data = {
                "status": "COMPLETED", 
                "book_id": book_id,
                "total_characters": len(successful_characters),
                "completed_at": datetime.now().isoformat(),
                "message": "캐릭터 생성이 완료되었습니다."
            }
            await sync_to_async(script_cache.set)(task_key, completed_data, timeout=7200)
            await self.send_character_task_event(task_id, "completed", completed_data)
            
            print(f"✅ [TASK COMPLETE] 캐릭터 생성 최종 완료 - Task ID: {task_id}, 생성된 캐릭터: {len(successful_characters)}명")
            
            return {
                "status": "success", 
                "task_id": task_id, 
                "characters_created": len(successful_characters),
                "characters": successful_characters
            }
            
        except Exception as e:
            error_msg = f"캐릭터 생성 중 오류 발생: {str(e)}"
            print(f"❌ [ERROR] {error_msg}")
            
            await sync_to_async(script_cache.set)(task_key, {
                "status": "FAILED", 
                "error_message": error_msg
            }, timeout=7200)
            await self.send_character_task_event(task_id, "error", {"message": error_msg})
            
            raise
    
    async def generate_script_async(self, character_id: int, scene_count: int = 3, script_id: str = None):
        """
        asyncio를 사용한 대본 생성
        """
        task_id = str(uuid.uuid4())
        script_cache = caches['script_cache']
        
        # script_id 처리
        if not script_id:
            script_id = str(uuid.uuid4())
        
        task_key = f"task:{task_id}"
        script_key = f"script:{script_id}"
        
        print(f"[DEBUG] 대본 AsyncIO 작업 시작됨 - character_id: {character_id}, task_id: {task_id}, script_id: {script_id}")
        
        try:
            # 1. 초기 상태 저장
            init_data = {
                "status": "PROCESSING",
                "character_id": character_id,
                "scene_count": scene_count,
                "script_id": script_id,
                "started_at": datetime.now().isoformat(),
                "message": "대본 생성 중..."
            }
            await sync_to_async(script_cache.set)(task_key, init_data, timeout=3600)
            
            script_init_data = {
                "character_id": character_id,
                "characterId": character_id,
                "character_name": "",
                "script_id": script_id,
                "status": "PROCESSING",
                "started_at": datetime.now().isoformat(),
                "message": "대본 생성 중...",
                "scene_count": scene_count,
                "scenes": []
            }
            await sync_to_async(script_cache.set)(script_key, script_init_data, timeout=2000)
            
            print(f"📝 [TASK START] 대본 생성 시작 - Character ID: {character_id}, Task ID: {task_id}")
            
            # Character 조회 (비동기)
            character = await sync_to_async(Character.objects.get)(id=character_id, is_deleted=False)
            print(f"🎭 [CHARACTER] 캐릭터 정보 로드 - 이름: '{character.characterName}', 주인공: {character.isMain}")
            
            # 조연 캐릭터 정보 수집 (비동기)
            sub_characters_queryset = Character.objects.filter(
                book=character.book, isMain=False, is_deleted=False
            ).exclude(id=character.id)
            sub_characters = await sync_to_async(list)(sub_characters_queryset)
            print(f"👥 [SUB CHARACTERS] 조연 캐릭터 {len(sub_characters)}명 수집")
            
            # 작업 시작 이벤트 전송
            await self.send_character_task_event(task_id, "started", {
                "message": "대본 생성 시작됨", 
                "character_id": character_id,
                "character_name": character.characterName,
                "script_id": script_id,
                "scene_count": scene_count
            })
            
            # 2. Gemini API로 대본 생성 (CPU bound 작업을 별도 스레드에서)
            print("🤖 [STEP 1/2] Gemini API 대본 생성 시작...")
            
            await self.send_character_task_event(task_id, "progress", {
                "message": "Gemini API로 대본 생성 중...",
                "step": "gemini_generation",
                "character_name": character.characterName,
                "script_id": script_id
            })
            
            loop = asyncio.get_event_loop()
            raw_text = await loop.run_in_executor(
                None,
                generate_scenes_with_gemini,
                character,
                sub_characters,
                scene_count
            )
            print(f"📄 [STEP 1/2] Gemini API 응답 완료 - 응답 길이: {len(raw_text)} 문자")
            
            # 3. 파싱 및 Redis 캐시 저장
            print("📋 [STEP 2/2] 대본 파싱 및 캐싱 시작...")
            
            await self.send_character_task_event(task_id, "progress", {
                "message": "대본 파싱 및 저장 중...",
                "step": "parsing",
                "character_name": character.characterName,
                "script_id": script_id
            })
            
            parsed_result = await loop.run_in_executor(None, parse_scene_list, raw_text)
            
            scene_texts = parsed_result.get("scenes", [])
            print(f"🔍 [PARSING] 파싱 완료 - Script ID: {script_id}, 장면 수: {len(scene_texts)}")
            
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
                    "lines": scene.get("lines"),
                    "rewriting_prompt": scene.get("rewriting_prompt"),
                    "rewriting_id": scene.get("rewriting_id")
                })
            
            # 4. 대본을 Redis에 저장
            script_cache_data = {
                "characterId": character_id,
                "character_id": character_id,
                "character_name": character.characterName,
                "scenes": generated_scenes,
                "scene_count": len(generated_scenes),
                "script_id": script_id,
                "status": "COMPLETED",
                "started_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "message": "대본 생성이 완료되었습니다."
            }
            await sync_to_async(script_cache.set)(script_key, script_cache_data, timeout=2000)
            print(f"💾 [CACHE] Redis 대본 캐싱 완료 - Key: {script_key}")
            
            # 5. 완료 상태 저장
            completed_data = {
                "status": "COMPLETED",
                "character_id": character_id,
                "character_name": character.characterName,
                "scene_count": scene_count,
                "script_id": script_id,
                "started_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "message": "대본 생성이 완료되었습니다."
            }
            await sync_to_async(script_cache.set)(task_key, completed_data, timeout=3600)
            
            # 6. 완료 이벤트 전송
            await self.send_character_task_event(task_id, "completed", {
                "message": "대본 생성이 완료되었습니다.",
                "script_id": script_id,
                "character_name": character.characterName,
                "scene_count": len(generated_scenes),
                "scenes": generated_scenes
            })
            
            print(f"✅ [TASK COMPLETE] 대본 생성 완료 - Task ID: {task_id}, Script ID: {script_id}")
            
            return {
                "status": "success",
                "task_id": task_id,
                "character_id": character_id,
                "script_id": script_id,
                "scene_count": len(generated_scenes),
                "scenes": generated_scenes
            }
            
        except Exception as e:
            error_msg = f"대본 생성 중 오류 발생: {str(e)}"
            print(f"❌ [ERROR] {error_msg}")
            
            # 실패 상태 저장
            error_data = {
                "status": "FAILED",
                "character_id": character_id,
                "scene_count": scene_count,
                "script_id": script_id,
                "started_at": datetime.now().isoformat(),
                "failed_at": datetime.now().isoformat(),
                "error_message": error_msg
            }
            await sync_to_async(script_cache.set)(task_key, error_data, timeout=3600)
            
            # 오류 이벤트 전송
            await self.send_character_task_event(task_id, "error", {"message": error_msg})
            
            raise


# 전역 프로세서 인스턴스
character_processor = AsyncCharacterProcessor()


async def start_character_generation_task(book_id: int):
    """
    asyncio 캐릭터 생성 태스크를 시작하는 함수
    """
    task = asyncio.create_task(
        character_processor.generate_characters_async(book_id)
    )
    return task


async def start_script_generation_task(character_id: int, scene_count: int = 3, script_id: str = None):
    """
    asyncio 대본 생성 태스크를 시작하는 함수
    """
    task = asyncio.create_task(
        character_processor.generate_script_async(character_id, scene_count, script_id)
    )
    return task
