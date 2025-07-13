from django.urls import path
from .views import BookFromTextView, BookFromPdfView

urlpatterns = [
    path('text/', BookFromTextView.as_view()),
    path('pdf/', BookFromPdfView.as_view()),


]
