from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import BookCreateSerializer

# Create your views here.

# 책 입력 API 2가지를 정의함
# 나중에 구현할 기능이기에 추후에 수정이 반드시 필요!!
''' 책 텍스트로 입력시 book을 생성하는 API '''
class BookTextUploadView(APIView):
    def post(self, request):
        serializer = BookCreateSerializer(data=request.data)
        if serializer.is_valid():
            book = serializer.save()
            return Response({
                "book_id": book.id,
                "title": book.title,
                "content": book.content,
                "book_url": None
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "error",
            "error_code": 400,
            "message": "입력한 정보 형식이 올바르지 않습니다."
        }, status=status.HTTP_400_BAD_REQUEST)
    

class BookFromPdfView(APIView):
    def post(self, request):
        # PDF 기반 book 생성 로직
        return Response({"message": "Book created from PDF"}, status=201)
    

