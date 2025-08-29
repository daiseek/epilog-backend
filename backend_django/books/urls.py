from django.urls import path
from .views import BookFromPdfView, BookOfficialView, BookFromPdfAsyncView, BookFromPdfAsyncioView  # BookStatusView는 더 이상 사용 안함
# from .views import BookVideosView  # 비디오 기능 비활성화
from . import views

from characters.views import (
    CharacterConditionalCreateOrListView,
    CharacterGenerateAsyncView
)
from characters.asyncio_views import (
    CharacterGenerateAsyncioView
)
urlpatterns = [
    # path('text', BookTextUploadView.as_view()), # 책 텍스트 업로드 API

    path('pdf', BookFromPdfView.as_view()), # 책 PDF 업로드 API(동기)
    
    path('pdf/async', BookFromPdfAsyncView.as_view()), # 책 PDF 업로드 API (Celery 비동기)
    path('pdf/asyncio', BookFromPdfAsyncioView.as_view()), # 책 PDF 업로드 API (AsyncIO 비동기)

    path('official', BookOfficialView.as_view()), # 공용책 정보 API

    # path('<int:book_id>/videos', BookVideosView.as_view()), # 책 동영상 API - 비디오 기능 비활성화

    # === 캐릭터 관련 RESTful API => 기존에 Characters 폴더에 있었지만, RESTful 설계를 위해 옮겼습니다.===
    path('<int:book_id>/characters', CharacterConditionalCreateOrListView.as_view()), # 캐릭터 조회/생성 (동기)
    path('<int:book_id>/characters/async', CharacterGenerateAsyncView.as_view()), # 캐릭터 생성 (Celery 비동기)
    path('<int:book_id>/characters/asyncio', CharacterGenerateAsyncioView.as_view()), # 캐릭터 생성 (AsyncIO 비동기)
    # === task_id 기반 실시간 알림 (직접 SSE 구현) ===
    path('tasks/<str:task_id>/eventstream', views.task_eventstream_view), # 범용 작업 상태 (task_id 기반)

]
