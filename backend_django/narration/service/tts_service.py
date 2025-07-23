import os
import requests
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
import uuid
from io import BytesIO

load_dotenv()
API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not API_KEY:
    raise ValueError("ELEVENLABS_API_KEY 환경 변수가 설정되지 않았습니다.")

elevenlabs_client = ElevenLabs(api_key=API_KEY)

def generate_tts_audio_bytes(
    text: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",  # V2가 더 안정적
    stability: float = 0.4,  # 중간값으로 안정성 확보  
    similarity_boost: float = 0.8,  # 적당한 유사성
    style: float = 0.0  # 스타일 없음으로 안정성 확보
) -> bytes:
    
    """
    ElevenLabs TTS를 사용하여 오디오 바이트를 생성하는 함수
    한국어 텍스트 처리를 위해 최적화됨
    """
    
    # print(f"🎤 [TTS 시작] 전체 텍스트: {repr(text)}")
    # print(f"   텍스트 길이: {len(text)}자, 음성 ID: {voice_id}")

    try:
        # 텍스트 전처리
        processed_text = text.strip()
        if not processed_text:
            raise ValueError("빈 텍스트는 처리할 수 없습니다.")
        
        # 한국어 텍스트 감지 및 특별 처리
        has_korean = any('\uac00' <= char <= '\ud7af' for char in processed_text)
        if has_korean:
            # print(f"🇰🇷 [TTS] 한국어 텍스트 감지됨 - 안정적인 설정 적용")
            # 한국어에 안정적인 설정 (극단값 피하기)
            model_id = "eleven_multilingual_v2" 
            stability = 0.8  # 중간값으로 안정성 확보
            similarity_boost = 0.8  # 적당한 유사성
            style = 0.0  # 스타일 제거
            # print(f"   한국어 최적화 설정 적용됨")
        
        # print(f"🔧 [TTS 설정] 모델: {model_id}, stability: {stability}, similarity: {similarity_boost}")
        # print(f"   처리할 텍스트: {repr(processed_text)}")

        # ElevenLabs SDK의 stream 방식 사용 (더 안전한 청크 수집)
        print(f"🚀 [TTS 요청] ElevenLabs stream API 호출 시작...")
        audio_stream = elevenlabs_client.text_to_speech.convert(
            text=processed_text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings={
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": False
            },
            output_format="mp3_44100_128"
        )
        # print(f"✅ [TTS 요청] stream 객체 생성 완료")
        
        # 스트리밍된 오디오 데이터를 안전하게 수집
        audio_chunks = []
        chunk_count = 0
        total_bytes = 0
        
        # print(f"📡 [TTS 스트리밍] 청크 수집 시작...")
        
        try:
            for chunk in audio_stream:
                if isinstance(chunk, bytes) and len(chunk) > 0:
                    audio_chunks.append(chunk)
                    chunk_count += 1
                    total_bytes += len(chunk)
                    
                    # 진행 상황 출력
                    if chunk_count <= 5 or chunk_count % 10 == 0:
                        print(f"   청크 {chunk_count}: {len(chunk)} bytes 받음")
            
            # 모든 청크를 하나로 결합
            audio_data = b"".join(audio_chunks)
            # print(f"📦 [TTS 수집] 총 {chunk_count}개 청크 결합 완료")
            
        except Exception as stream_error:
            # print(f"❌ [TTS 스트리밍 오류] {stream_error}")
            # 혹시 부분적으로 수집된 데이터라도 사용 시도
            if audio_chunks:
                audio_data = b"".join(audio_chunks)
                # print(f"⚠️ [TTS 복구] 부분 데이터 사용: {len(audio_chunks)}개 청크")
            else:
                raise Exception(f"스트리밍 실패: {stream_error}")
        
        # print(f"✅ [TTS 완료] 최종 오디오 크기: {len(audio_data)} bytes")
        
        if len(audio_data) == 0:
            raise Exception("오디오 데이터가 생성되지 않았습니다.")
        
        # if len(audio_data) < 1000:  # 1KB 미만이면 의심스러움
        #     print(f"⚠️ [TTS 경고] 오디오 데이터가 너무 작습니다: {len(audio_data)} bytes")
        
        return audio_data

    except Exception as e:
        print(f"❌ [TTS 오류] {type(e).__name__}: {str(e)}")
        print(f"   문제 텍스트: {repr(text)}")
        raise Exception(f"TTS 생성 실패: {str(e)}")
