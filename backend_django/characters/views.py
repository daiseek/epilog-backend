from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import caches
from .gpt_client import generate_scenes_with_gpt, parse_scene_list
import uuid


from .models import Character
from books.models import Book

# Create your views here.

''' 캐릭터 생성 혹은 조회 기능'''
class CharacterConditionalCreateOrListView(APIView):
    
    """
    POST /characters/books/{bookId}
    캐릭터가 존재하면 목록 조회, 없으면 새로 생성하는 함수
    """
    def post(self, request, book_id):
        try:
            book = Book.objects.get(id=book_id)
        except Book.DoesNotExist:
            return Response({'error': 'Book not found'}, status=404)

        # 캐릭터가 존재하면 목록 조회
        existing_characters = Character.objects.filter(book=book, is_deleted=False)
        if existing_characters.exists():
            data = [
                {
                    'id': character.id,
                    'characterName': character.characterName,
                    'isMain': character.isMain,
                    'age': character.age,
                    'gender': character.gender,
                    'characterDescription': character.characterDescription,
                }
                for character in existing_characters
            ]
            return Response(data, status=200)

        # 없으면 새로 생성
        # 나중에 GPT로 생성하는 로직 추가 필요!!
        data = request.data
        character = Character.objects.create(
            characterName=data.get('characterName'),
            isMain=data.get('isMain', False),
            age=data.get('age'),
            gender=data.get('gender'),
            characterDescription=data.get('characterDescription'),
            book=book
        )
        return Response({'id': character.id, 'characterName': character.characterName}, status=201)
    

'''대본 생성 기능'''
class ScriptGenerateView(APIView):
   def post(self, request, character_id):
        try: # 주연 캐릭터 조회
            character = Character.objects.get(id=character_id, is_deleted=False)
        except Character.DoesNotExist:
            return Response({'error': 'Character not found'}, status=404)

        # 장면 개수 결정 
        # 추후 수정 필요!!
        desc_length = len(character.characterDescription)
        scene_count = 2 if desc_length < 100 else 3 if desc_length < 200 else 4 if desc_length < 400 else 5

        # 조연 캐릭터 정보 수집
        sub_characters = Character.objects.filter(
            book=character.book, isMain=False, is_deleted=False
        ).exclude(id=character.id)

        sub_info = "\n".join([
            f"- {c.characterName} ({c.age}살, {c.gender}): {c.characterDescription}"
            for c in sub_characters
        ]) if sub_characters.exists() else None

        # GPT 호출
        try:
            raw_text = generate_scenes_with_gpt(
                main_character=character,
                sub_characters=sub_characters,
                scene_count=scene_count,
            )
        except Exception as e:
            return Response({'error': f'GPT 호출 실패: {str(e)}'}, status=500)

        # 파싱 및 저장
        scene_texts = parse_scene_list(raw_text)
        generated_scenes = [
        {
        "sceneId": scene.get("scene"),
        "lines": scene.get("lines"),
        "video_job_id": f"job-{uuid.uuid4()}"
        }
        for scene in scene_texts
        ]

        cache_key = f"script:{character_id}"
        script_cache = caches['script_cache']
        script_cache.set(cache_key, generated_scenes, timeout=600)

        return Response({
            "characterId": character_id,
            "scenes": generated_scenes
        }, status=201)