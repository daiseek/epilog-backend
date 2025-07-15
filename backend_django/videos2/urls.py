from django.urls import path
from .views import TextToSpeechView, ActorListView

urlpatterns = [
    path('tts/', TextToSpeechView.as_view(), name='text_to_speech'),
    path('actors/', ActorListView.as_view(), name='actor_list'),
]