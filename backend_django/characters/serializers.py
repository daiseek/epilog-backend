from rest_framework import serializers
from .models import Character, CharacterScene

class CharacterSceneSerializer(serializers.ModelSerializer):
    class Meta:
        model = CharacterScene
        fields = ['id', 'scene_content', 'start_page', 'finish_page']

class CharacterSerializer(serializers.ModelSerializer):
    scenes = CharacterSceneSerializer(many=True, read_only=True)
    
    class Meta:
        model = Character
        fields = ['id', 'characterName', 'isMain', 'age', 'gender', 'characterDescription', 'scenes']

# Swagger 문서화를 위한 응답 Serializer들
class CharacterErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="에러 메시지")

class CharacterDetailedErrorResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="에러 상태")
    error_code = serializers.IntegerField(help_text="에러 코드")
    message = serializers.CharField(help_text="에러 메시지")

class ScriptGenerateResponseSerializer(serializers.Serializer):
    script_id = serializers.CharField(help_text="생성된 스크립트 ID")
    characterId = serializers.IntegerField(help_text="캐릭터 ID")
    scenes = serializers.ListField(
        help_text="생성된 장면들",
        child=serializers.DictField(
            child=serializers.CharField(),
            help_text="장면 정보 (background, mood, style, camera, soundtrack, characters, lines, rewriting_prompt 등)"
        )
    )

# 비동기 대본 생성을 위한 응답 Serializer들 (Redis 기반)
class ScriptAsyncResponseSerializer(serializers.Serializer):
    task_id = serializers.CharField(help_text="Celery 태스크 ID")
    character_id = serializers.IntegerField(help_text="캐릭터 ID")
    character_name = serializers.CharField(help_text="캐릭터 이름")
    scene_count = serializers.IntegerField(help_text="생성할 장면 수")
    message = serializers.CharField(help_text="상태 메시지")

class ScriptTaskStatusResponseSerializer(serializers.Serializer):
    task_id = serializers.CharField(help_text="Celery 태스크 ID")
    character_id = serializers.IntegerField(help_text="캐릭터 ID")
    character_name = serializers.CharField(help_text="캐릭터 이름", allow_null=True)
    status = serializers.CharField(help_text="처리 상태 (PROCESSING, COMPLETED, FAILED)")
    script_id = serializers.CharField(help_text="완성된 스크립트 ID", allow_null=True)
    scene_count = serializers.IntegerField(help_text="생성할 장면 수")
    scenes = serializers.ListField(
        help_text="완성된 대본 장면들 (COMPLETED 상태일 때만 포함)",
        child=serializers.DictField(
            child=serializers.CharField(),
            help_text="장면 정보 (background, mood, style, camera, soundtrack, characters, rewriting_prompt 등)"
        ),
        required=False,
        allow_null=True
    )
    error_message = serializers.CharField(help_text="오류 메시지", allow_null=True)
    message = serializers.CharField(help_text="상태 메시지", allow_null=True)
    started_at = serializers.CharField(help_text="시작일시", allow_null=True)
    completed_at = serializers.CharField(help_text="완료일시", allow_null=True)
    failed_at = serializers.CharField(help_text="실패일시", allow_null=True)