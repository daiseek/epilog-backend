import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path, re_path
import django_eventstream # django_eventstream 모듈 전체를 임포트

# 환경변수에 따라 설정 파일 선택
env = os.environ.get('DJANGO_ENV', 'dev')

if env == 'prod':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_prod')
else:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings_dev')

# Django의 기본 ASGI 애플리케이션을 먼저 가져옵니다.
django_asgi_app = get_asgi_application()

# django_eventstream 애플리케이션을 AuthMiddlewareStack으로 감싸서 정의
eventstream_app = AuthMiddlewareStack(
    URLRouter(django_eventstream.urls.urlpatterns)
)

# 이제 ProtocolTypeRouter를 사용하여 프로토콜에 따라 요청을 분기합니다.
application = ProtocolTypeRouter({
    "http": URLRouter([
        path('events/', eventstream_app), # 미리 정의된 eventstream_app 사용
        re_path(r'^', django_asgi_app), # Django의 기본 ASGI 앱으로 폴백
    ]),
    # (나중에 웹소켓 등을 추가한다면 여기에 'websocket': AuthMiddlewareStack(URLRouter([...])) 을 추가할 수 있습니다.)
})