from django.urls import path
from .views import (
    CharacterConditionalCreateOrListView, 
    ScriptGenerateView,
    ScriptGenerateAsyncView,
    ScriptTaskStatusView
)

urlpatterns = [
    path('books/<int:book_id>/', CharacterConditionalCreateOrListView.as_view()), # 캐릭터 생성 혹은 조회 기능
    path('<int:character_id>/script/sync/', ScriptGenerateView.as_view()),  # 대본 생성 기능 (동기)
    path('<int:character_id>/scripts/', ScriptGenerateAsyncView.as_view()),  # 대본 생성 기능 (비동기)
    path('tasks/<str:task_id>/status/', ScriptTaskStatusView.as_view()),  # 대본 생성 상태 확인 (Redis 기반)

]
