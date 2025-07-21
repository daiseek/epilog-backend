# users/models.py


from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    # login_id는 AbstractUser의 username 필드를 사용
    # password는 AbstractUser에 이미 포함됨
    # created_at는 AbstractUser의 date_joined 필드를 사용
    
    nickname = models.CharField("닉네임", max_length=50, null=False, blank=False, default='default_nickname')
    updated_at = models.DateTimeField("수정일", auto_now=True)
    is_deleted = models.BooleanField("삭제여부", default=False)
    
    # 향후 역할 시스템을 위한 예시 필드들 (필요시 추가)
    # ROLE_CHOICES = [
    #     ('user', '일반사용자'),
    #     ('admin', '관리자'),
    #     ('moderator', '중간관리자'),
    # ]
    # role = models.CharField("역할", max_length=20, choices=ROLE_CHOICES, default='user')
    # is_premium = models.BooleanField("프리미엄 회원", default=False)
    
    # 기존 필드 제거
    # short_description = models.TextField("소개글", blank=True)
    
    class Meta:
        db_table = 'users'
        verbose_name = '사용자'
        verbose_name_plural = '사용자들'
    
    def __str__(self):
        return f"{self.username} ({self.nickname})"
    
    def delete(self, using=None, keep_parents=False):
        """소프트 삭제 구현"""
        self.is_deleted = True
        self.save()
        
    def hard_delete(self, using=None, keep_parents=False):
        """실제 삭제"""
        super().delete(using=using, keep_parents=keep_parents)
