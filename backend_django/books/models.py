from django.db import models

# Create your models here.
class Book(models.Model):
    # Book 모델의 속성 정의
    title = models.CharField(max_length=255) # 책 제목
    content = models.TextField(max_length=1000, null=False, blank=False) # 책 내용
    description = models.TextField(max_length=500, null=False, blank=False) # 책 설명
    created_at = models.DateTimeField(auto_now_add=True) # 생성일자 - 자동으로 관리 
    updated_at = models.DateTimeField(auto_now=True) # 수정일자 - 자동으로 관리
    is_deleted = models.BooleanField(default=False) # 삭제 여부 - 기본값은 False(0)


    def __str__(self):
        return self.title
