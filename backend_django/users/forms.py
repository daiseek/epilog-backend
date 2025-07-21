# users/forms.py

# ========== 기존 Django Form들 (주석처리) ==========
# JWT API 환경에서는 DRF serializer를 사용하므로 Django Form은 불필요

# from django import forms
# from django.core.exceptions import ValidationError
# from users.models import User

# class LoginForm(forms.Form):
#     login_id = forms.CharField(min_length=3,
#     widget=forms.TextInput(attrs={'placeholder': '로그인 ID (3자리 이상)'}))
#     password = forms.CharField(min_length=4,
#     widget=forms.PasswordInput(attrs={'placeholder': '비밀번호 (4자리 이상)'}))


# class SignupForm(forms.Form):
#     login_id = forms.CharField(
#         label='로그인 ID',
#         widget=forms.TextInput(attrs={'placeholder': '로그인 ID'})
#     )
#     password1 = forms.CharField(
#         label='비밀번호',
#         widget=forms.PasswordInput(attrs={'placeholder': '비밀번호'})
#     )
#     password2 = forms.CharField(
#         label='비밀번호 확인',
#         widget=forms.PasswordInput(attrs={'placeholder': '비밀번호 확인'})
#     )
#     nickname = forms.CharField(
#         label='닉네임',
#         widget=forms.TextInput(attrs={'placeholder': '닉네임'})
#     )

#     def clean_login_id(self):
#         login_id = self.cleaned_data['login_id']
#         if User.objects.filter(username=login_id, is_deleted=False).exists():
#             raise ValidationError(f"입력한 로그인 ID({login_id})는 이미 사용 중입니다.")
#         return login_id

#     def clean(self):
#         cleaned_data = super().clean()
#         password1 = cleaned_data.get('password1')
#         password2 = cleaned_data.get('password2')

#         if password1 and password2 and password1 != password2:
#             self.add_error('password2', '비밀번호와 비밀번호 확인란의 값이 다릅니다.')

#     def save(self):
#         login_id = self.cleaned_data['login_id']
#         password1 = self.cleaned_data['password1']
#         nickname = self.cleaned_data['nickname']

#         user = User.objects.create_user(
#             username=login_id,  # login_id를 username 필드에 저장
#             password=password1,
#             nickname=nickname
#         )
#         return user
