from django.urls import path, include
from .views import (
    VideoListView, 
    VideoBookmarkToggleView, 
    BookmarkedVideoListView, 
    ScriptCacheView, 
    VideoDeleteView,
    EventTestView
)


urlpatterns = [
    # SSE events stream
    path('events/', include('django_eventstream.urls')),

    # Video list and creation
    path('', VideoListView.as_view(), name='list_videos'),

    # Bookmark operations
    path('bookmarks/<int:videoId>', VideoBookmarkToggleView.as_view(), name='toggle_bookmark'),
    path('bookmarks/bookmarked', BookmarkedVideoListView.as_view(), name='list_bookmarked_videos'),

    # Video deletion
    path('<int:videoId>/', VideoDeleteView.as_view(), name='delete_video'),

    # Script caching
    path('cache-script/', ScriptCacheView.as_view(), name='cache_script'),


    path('test-event/', EventTestView.as_view(), name='event-test')
]