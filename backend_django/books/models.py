from django.db import models

# Create your models here.
class Book(models.Model):
    # 처리 상태 선택지
    PROCESSING_STATUS_CHOICES = [
        ('PENDING', '대기 중'),
        ('PROCESSING', '처리 중'),
        ('COMPLETED', '완료'),
        ('FAILED', '실패'),
    ]

    # Book 모델의 속성 정의
    title = models.CharField(max_length=255) # 책 제목
    content = models.TextField(max_length=1000, null=True, blank=True) # 책 내용 (처리 완료 후 채워짐)
    pdf_url = models.URLField(max_length=500, null=True, blank=True) # S3에 저장된 PDF URL
    processing_status = models.CharField(
        max_length=20, 
        choices=PROCESSING_STATUS_CHOICES, 
        default='PENDING',
        help_text='PDF 처리 상태'
    ) # 처리 상태
    task_id = models.CharField(max_length=255, null=True, blank=True) # Celery 태스크 ID
    error_message = models.TextField(null=True, blank=True) # 오류 메시지
    created_at = models.DateTimeField(auto_now_add=True) # 생성일자 - 자동으로 관리 
    updated_at = models.DateTimeField(auto_now=True) # 수정일자 - 자동으로 관리
    is_deleted = models.BooleanField(default=False) # 삭제 여부 - 기본값은 False(0)

    class Meta:
        db_table = 'books'
        verbose_name = '책'
        verbose_name_plural = '책들'
        ordering = ['-created_at']  # 최신순 정렬

    def __str__(self):
        return self.title

