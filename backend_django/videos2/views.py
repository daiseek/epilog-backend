
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .typecast_service import text_to_speech, get_actors

class TextToSpeechView(APIView):
    def post(self, request, *args, **kwargs):
        text = request.data.get("text")
        actor_id = request.data.get("actor_id")
        title = request.data.get("title")

        if not text or not actor_id or not title:
            return Response({"error": "Text, actor_id, and title are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            result = text_to_speech(text, actor_id, title)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ActorListView(APIView):
    def get(self, request, *args, **kwargs):
        try:
            actors = get_actors()
            return Response(actors, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
