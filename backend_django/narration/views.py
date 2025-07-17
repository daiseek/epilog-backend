import uuid
import os
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from narration.service.tts_service import generate_tts
from narration.voice_selector import get_voice_id
from characters.models import Character
from narration.common.s3_client import upload_file_to_s3

''' 음성 생성 API 뷰 '''
class GenerateVoiceAPIView(APIView):
    
    # self: GenerateVoiceAPIView 클래스의 인스턴스
    # request: HTTP 요청 객체
    def post(self, request): 
        try:
            character_id = request.data.get("characterId") # request에서 characterId를 가져옴
            lines = request.data.get("lines", []) # request에서 lines를 가져오고, 기본값은 빈 리스트로 설정

            if not character_id or not lines:
                return Response({"error": "characterId와 lines는 필수입니다."}, status=400)

            character = Character.objects.get(id=character_id, is_deleted=False)
            
            # Character 필드 안전성 검사
            gender = character.gender
            age = character.age
            
            print(f"Character: {character.characterName}")
            print(f"Raw Gender: {repr(gender)} (type: {type(gender)})")
            print(f"Raw Age: {repr(age)} (type: {type(age)})")
            
            # gender 값 검증 및 정규화
            if gender is None:
                return Response({"error": "Character gender is None"}, status=400)
                
            # age 값 검증
            if age is None:
                return Response({"error": "Character age is None"}, status=400)
                
            try:
                voice_id = get_voice_id(gender, age)
                print(f"Voice ID: {voice_id}")
            except ValueError as ve:
                return Response({"error": f"Voice selection error: {str(ve)}"}, status=400)
            
            if not voice_id:
                return Response({
                    "error": f"voice_id not found for gender: '{gender}', age: {age}"
                }, status=400)

            audio_urls = []

            for line in lines:
                speaker = line.get("speaker")
                text = line.get("text")

                # 입력 값 검증
                if not speaker:
                    return Response({"error": "'speaker'는 필수입니다."}, status=400)
                    
                if text is None:
                    return Response({"error": "'text'는 필수입니다."}, status=400)

                # text를 안전하게 문자열로 변환
                if not isinstance(text, str):
                    print(f"Warning: text is not string, converting from {type(text)}: {repr(text)}")
                    text = str(text)
                
                text = text.strip()
                if not text:
                    return Response({"error": "'text'는 빈 문자열일 수 없습니다."}, status=400)

                print(f"Processing line: {repr(text)} for speaker: {speaker}")
                
                try:
                    local_filename = f"/tmp/{uuid.uuid4()}.mp3"
                    generate_tts(text, voice_id, local_filename)
                except Exception as tts_error:
                    print(f"TTS Error: {tts_error}")
                    return Response({"error": f"TTS 생성 오류: {str(tts_error)}"}, status=500)

                try:
                    s3_key = f"tts/{uuid.uuid4()}.mp3"
                    audio_url = upload_file_to_s3(local_filename, s3_key)
                    print(f"S3 upload successful: {audio_url}")
                    
                    audio_urls.append({
                        "sceneId": line.get("sceneId"),
                        "speaker": speaker,
                        "audioUrl": audio_url
                    })
                except Exception as s3_error:
                    print(f"S3 Upload Error: {s3_error}")
                    return Response({"error": f"S3 업로드 오류: {str(s3_error)}"}, status=500)
                finally:
                    # 임시 파일 정리
                    try:
                        if os.path.exists(local_filename):
                            os.remove(local_filename)
                            print(f"Cleaned up temp file: {local_filename}")
                    except Exception as cleanup_error:
                        print(f"Cleanup warning: {cleanup_error}")

            # return 문을 for 루프 밖으로 이동
            return Response({"status": "ok", "results": audio_urls}, status=200)

        except Character.DoesNotExist:
            return Response({"error": "Character not found"}, status=404)
        except ValueError as ve:
            return Response({"error": f"Validation error: {str(ve)}"}, status=400)
        except Exception as e:
            print(f"Exception occurred: {type(e).__name__}: {str(e)}")
            return Response({"error": str(e)}, status=500)
