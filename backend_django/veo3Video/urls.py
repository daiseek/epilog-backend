from django.urls import path
from .views import TextToVideoView, VideoListView, VideoBookmarkToggleView, BookmarkedVideoListView, VideoGenerationFromScriptView, CombineVideosView, FullStoryGenerationView, ScriptCacheView

# veo3Video 앱의 URL 패턴을 정의합니다.
# 이 파일은 config/urls.py에서 include되어 사용됩니다.
urlpatterns = [
    # TextToVideoView는 POST 요청을 처리, 텍스트로부터 비디오 생성 요청.
    # # 'generate/' 경로에 대한 URL 패턴 정의, http://localhost:28000/voe3Video/ + generate/ 으로 api 요청
    # name='generate_video'는 이 URL 패턴의 이름을 지정, 템플릿이나 다른 코드에서 사용할 수 있도록 alias.
    path('generate/', TextToVideoView.as_view(), name='generate_video'),
    
    # TextToVideoView는 POST 요청을 처리, 데이터베이스에 저장된 비디오 목록 반환.
    # # 'generate/' 경로에 대한 URL 패턴 정의, http://localhost:28000/voe3Video/ + videos/ 으로 api 요청
    # name='list_videos'는 이 URL 패턴의 이름을 지정, 템플릿이나 다른 코드에서 사용할 수 있도록 alias
    path('videos/', VideoListView.as_view(), name='list_videos'),

    path('bookmarks/videos/<int:videoId>', VideoBookmarkToggleView.as_view(), name = 'toggle_bookmark'),
    path('bookmarks/bookmarked', BookmarkedVideoListView.as_view(), name = 'list_bookmarked_videos'),
    path('generate/script/<str:script_id>/', VideoGenerationFromScriptView.as_view(), name='generate_video_from_script'),
    path('combine/', CombineVideosView.as_view(), name='combine_videos'),
    path('generate/full-story/', FullStoryGenerationView.as_view(), name='generate_full_story'),
    path('cache-script/', ScriptCacheView.as_view(), name='cache_script'),
]