# users/serializers.py

from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from users.models import User


class LoginSerializer(serializers.Serializer):
    """로그인용 Serializer"""
    login_id = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        login_id = attrs.get('login_id')
        password = attrs.get('password')
        
        if login_id and password:
            # login_id는 username 필드에 매핑됨
            user = authenticate(username=login_id, password=password)
            if not user:
                raise serializers.ValidationError('잘못된 로그인 ID 또는 비밀번호입니다.')
            if not user.is_active:
                raise serializers.ValidationError('비활성화된 계정입니다.')
            if user.is_deleted:
                raise serializers.ValidationError('삭제된 계정입니다.')
            attrs['user'] = user
            return attrs
        else:
            raise serializers.ValidationError('로그인 ID와 비밀번호를 모두 입력해주세요.')


class SignupSerializer(serializers.ModelSerializer):
    """회원가입용 Serializer"""
    login_id = serializers.CharField(source='username')
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['login_id', 'password', 'password_confirm', 'nickname']
        
    def validate_login_id(self, value):
        """로그인 ID 중복 검증"""
        if User.objects.filter(username=value, is_deleted=False).exists():
            raise serializers.ValidationError('이미 사용 중인 로그인 ID입니다.')
        return value
        
    def validate(self, attrs):
        password = attrs.get('password')
        password_confirm = attrs.get('password_confirm')
        
        if password != password_confirm:
            raise serializers.ValidationError('비밀번호가 일치하지 않습니다.')
        
        return attrs
    
    def create(self, validated_data):
        # password_confirm은 사용하지 않으므로 제거
        validated_data.pop('password_confirm', None)
        
        user = User.objects.create_user(
            username=validated_data['username'],  # login_id가 username으로 매핑됨
            password=validated_data['password'],
            nickname=validated_data['nickname']
        )
        return user


class UserSerializer(serializers.ModelSerializer):
    """사용자 정보용 Serializer"""
    login_id = serializers.CharField(source='username', read_only=True)
    created_at = serializers.DateTimeField(source='date_joined', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'login_id', 'nickname', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at'] 
