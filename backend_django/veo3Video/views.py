from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
# veo_service.py에서 비디오 생성 및 목록 조회 로직을 임포트합니다.
from .veo_service import list_videos
from .tasks import create_video_for_scene
from django.core.cache import caches
from characters.models import Character

from django.shortcuts import get_object_or_404
from .models import Video
from .serializers import VideoSerializer

class VideoGenerationFromScriptView(APIView):
    def post(self, request, script_id, *args, **kwargs):
        script_cache = caches['script_cache']
        cached_data = script_cache.get(f"script:{script_id}")

        if not cached_data:
            return Response({"error": "Script not found in cache or expired"}, status=status.HTTP_404_NOT_FOUND)

        character_id = cached_data.get('characterId')
        scenes = cached_data.get('scenes', [])

        if not character_id or not scenes:
            return Response({"error": "Invalid script data in cache"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            character = Character.objects.get(id=character_id)
        except Character.DoesNotExist:
            return Response({"error": f"Character with id {character_id} not found"}, status=status.HTTP_404_NOT_FOUND)

        for scene in scenes:
            prompt = scene.get('rewriting_prompt')
            scene_id = scene.get('sceneId')
            title = f"{character.characterName} - Scene {scene_id}"

            if prompt:
                create_video_for_scene.delay(character_id=character_id, prompt=prompt, title=title)

        return Response({"message": f"Video generation started for {len(scenes)} scenes."}, status=status.HTTP_202_ACCEPTED)


# 텍스트-투-비디오 생성 API 뷰
# POST 요청을 처리하여 텍스트 프롬프트로부터 비디오 생성을 시작합니다.
class TextToVideoView(APIView):
    def post(self, request, *args, **kwargs):
        # 요청 본문에서 'prompt'와 'title' 필드를 추출합니다.
        prompt = request.data.get("prompt")
        title = request.data.get("title")
        character_id = request.data.get("character_id")

        # [JWT 통합 예정] 여기에 JWT 방식으로 사용자 ID를 받아오는 기능 개발
        # 현재는 user_id를 None으로 설정하여 익명 사용자로 처리합니다.
        # 실제 구현 시에는 request.user.id 또는 JWT 토큰에서 사용자 ID를 추출하여 사용합니다.
        user_id = None

        # 필수 필드(prompt, title)가 누락되었는지 확인합니다.
        if not prompt or not title:
            # 필수 필드가 누락된 경우 400 Bad Request 응답을 반환합니다.
            return Response({"error": "Prompt and title are required"}, status=status.HTTP_400_BAD_REQUEST)

        create_video_for_scene.delay(character_id=character_id, prompt=prompt, title=title)

        return Response({"message": "Video generation started."}, status=status.HTTP_202_ACCEPTED)


# 비디오 목록 조회 API 뷰
# GET 요청을 처리하여 데이터베이스에 저장된 비디오 목록을 반환합니다.
class VideoListView(APIView):
    def get(self, request, *args, **kwargs):
        # [JWT 통합 예정] 여기에 JWT 방식으로 사용자 ID를 받아오는 기능 개발
        # 현재는 user_id를 None으로 설정하여 모든 비디오를 조회합니다.
        # 실제 구현 시에는 request.user.id 또는 JWT 토큰에서 사용자 ID를 추출하여 사용합니다.
        user_id = None

        try:
            # veo_service.py의 list_videos 함수를 호출하여 비디오 목록을 조회합니다.
            # user_id가 전달되면 해당 사용자의 비디오만 필터링됩니다.
            videos = list_videos(user_id=user_id)
            # 비디오 목록 조회가 성공하면 200 OK 응답과 함께 목록을 반환합니다.
            return Response(videos, status=status.HTTP_200_OK)
        except Exception as e:
            # 비디오 목록 조회 중 오류가 발생하면 500 Internal Server Error 응답을 반환합니다.
            # 오류 메시지는 클라이언트에게 전달됩니다.
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VideoBookmarkToggleView(APIView):
    def patch(self, request, videoId):
        video = get_object_or_404(Video, pk=videoId)
        video.is_bookmarked = not video.is_bookmarked
        video.save()
        serializer = VideoSerializer(video)
        return Response(serializer.data, status=status.HTTP_200_OK)

class BookmarkedVideoListView(APIView):
    def get(self, request):
        bookmarked_videos = Video.objects.filter(is_bookmarked=True)    # 북마크된 비디오만 가져옴
        serializer = VideoSerializer(bookmarked_videos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CombineVideosView(APIView):
    def post(self, request, *args, **kwargs):
        video_uris = request.data.get("video_uris")
        output_title = request.data.get("output_title")
        user_id = request.data.get("user_id") # Optional
        character_id = request.data.get("character_id") # Optional

        if not video_uris or not isinstance(video_uris, list) or not output_title:
            return Response({"error": "video_uris (list) and output_title are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Celery 태스크 호출
        from .tasks import combine_videos_task
        combine_videos_task.delay(video_uris, output_title, user_id, character_id)

        return Response({"message": "Video combination started."}, status=status.HTTP_202_ACCEPTED)
