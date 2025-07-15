from django.urls import path
from .views import TextToVideoView

urlpatterns = [
    path('generate/', TextToVideoView.as_view(), name='generate_video'),
]