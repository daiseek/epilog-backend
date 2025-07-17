from django.urls import path
from .views import GenerateVoiceAPIView


urlpatterns = [
    # endpoint: /narration/voice/
    path('voice/', GenerateVoiceAPIView.as_view(), name='generate_voice'),
]
