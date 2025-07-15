from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .veo_service import generate_video_from_text

class TextToVideoView(APIView):
    def post(self, request, *args, **kwargs):
        prompt = request.data.get("prompt")
        title = request.data.get("title")

        if not prompt or not title:
            return Response({"error": "Prompt and title are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 비디오 생성 시작
            result = generate_video_from_text(prompt, title)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
