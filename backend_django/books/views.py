from django.shortcuts import render
from rest_framework.views import APIView


# Create your views here.

# 책 입력 API 2가지를 정의함
# 나중에 구현할 기능이기에 추후에 수정이 반드시 필요!!
class BookFromTextView(APIView):
    def post(self, request):
        # 텍스트 기반 book 생성 로직
        return Response({"message": "Book created from text"}, status=201)

class BookFromPdfView(APIView):
    def post(self, request):
        # PDF 기반 book 생성 로직
        return Response({"message": "Book created from PDF"}, status=201)
    

