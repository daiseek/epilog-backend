import uuid
from typing import List, Dict, Any
from characters.models import Character
from narration.service.tts_service import generate_tts_audio_bytes
from narration.voice_selector import get_voice_id
from narration.common.s3_client import upload_audio_bytes_to_s3


def generate_narration_for_character(character_id: int, lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    영상 생성에서 호출할 수 있는 나레이션 생성 함수
    
    Args: 넣어야할 매개변수
        character_id (int): 캐릭터 ID
        lines (List[Dict]): 대사 리스트
            예시: [
                {"sceneId": 1, "speaker": "점순이", "text": "안녕하세요"},
                {"sceneId": 2, "speaker": "점순이", "text": "반갑습니다"}
            ]
    
    Returns: 반환값 -> audioUrl에서 나레이션을 가져와서 영상 합성에 사용
        List[Dict]: 나레이션 결과 리스트
            예시: [
                {
                    "sceneId": 1,
                    "speaker": "점순이", 
                    "text": "안녕하세요",
                    "audioUrl": "https://bucket.s3.amazonaws.com/tts/abc123.mp3"
                }
            ]
    
    Raises:
        ValueError: 입력값이 잘못된 경우
        Character.DoesNotExist: 캐릭터를 찾을 수 없는 경우
        Exception: TTS 생성 또는 S3 업로드 실패
    """
    
    # 입력 검증
    if not character_id:
        raise ValueError("character_id는 필수입니다.")
    
    if not lines or not isinstance(lines, list):
        raise ValueError("lines는 비어있지 않은 리스트여야 합니다.")
    
    # 캐릭터 조회
    try:
        character = Character.objects.get(id=character_id, is_deleted=False)
    except Character.DoesNotExist:
        raise Character.DoesNotExist(f"Character with id {character_id} not found")
    
    # 캐릭터 정보 검증 및 Voice ID 선택
    gender = character.gender
    age = character.age
    
    print(f"🎭 [나레이션 생성] 캐릭터: {character.characterName} (성별: {gender}, 나이: {age})")
    
    if not gender:
        raise ValueError(f"캐릭터 {character.characterName}의 성별 정보가 없습니다.")
    
    if not age:
        raise ValueError(f"캐릭터 {character.characterName}의 나이 정보가 없습니다.")
    
    # Voice ID 선택
    try:
        voice_id = get_voice_id(gender, age)
        print(f"🔊 [나레이션 생성] 선택된 음성 ID: {voice_id}")
    except Exception as e:
        raise ValueError(f"음성 선택 실패: {str(e)}")
    
    if not voice_id:
        raise ValueError(f"성별 '{gender}', 나이 {age}에 맞는 음성을 찾을 수 없습니다.")
    
    # 각 대사에 대해 나레이션 생성
    audio_results = []
    
    for idx, line in enumerate(lines):
        speaker = line.get("speaker")
        text = line.get("text")
        scene_id = line.get("sceneId")
        
        # 대사별 검증
        if not speaker:
            raise ValueError(f"{idx + 1}번째 대사: speaker가 필요합니다.")
        
        if not text:
            raise ValueError(f"{idx + 1}번째 대사: text가 필요합니다.")
        
        # 텍스트 정규화
        text = str(text).strip()
        if not text:
            raise ValueError(f"{idx + 1}번째 대사: 빈 텍스트는 처리할 수 없습니다.")
        
        print(f"🎤 [나레이션 생성] {idx + 1}/{len(lines)}: {text[:50]}...")
        
        try:
            # TTS 생성
            audio_bytes = generate_tts_audio_bytes(text, voice_id)
            
            # S3 업로드
            s3_key = f"tts/{uuid.uuid4()}.mp3"
            audio_url = upload_audio_bytes_to_s3(audio_bytes, s3_key)
            
            # 결과 추가
            audio_results.append({
                "sceneId": scene_id,
                "speaker": speaker,
                "text": text,
                "audioUrl": audio_url
            })
            
            print(f"✅ [나레이션 생성] {idx + 1}번째 완료: {audio_url}")
            
        except Exception as e:
            error_msg = f"{idx + 1}번째 대사 처리 중 오류 발생: {str(e)}"
            print(f"❌ [나레이션 생성] {error_msg}")
            raise Exception(error_msg)
    
    print(f"🎉 [나레이션 생성] 완료: 총 {len(audio_results)}개 파일 생성")
    return audio_results 