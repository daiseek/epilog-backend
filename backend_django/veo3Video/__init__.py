# veo3Video Django 애플리케이션 패키지
# 이 디렉토리는 Google Cloud Vertex AI의 Veo 3 API를 사용하여 텍스트-투-비디오(Text-to-Video) 기능을 구현하는 앱입니다.
#
# 주요 기능:
# - 텍스트 프롬프트를 기반으로 비디오 생성 요청
# - 생성된 비디오의 메타데이터(URI, 프롬프트, 제목 등)를 데이터베이스에 저장
# - 저장된 비디오 목록을 조회하고 GCS 서명된 URL을 통해 접근 가능하도록 제공
#
# 포함된 파일:
# - models.py: 비디오 메타데이터를 저장하기 위한 Django 모델 정의
# - views.py: API 엔드포인트 (비디오 생성, 목록 조회) 정의
# - urls.py: API 엔드포인트에 대한 URL 라우팅 설정
# - veo_service.py: Google Cloud Veo 3 API 및 GCS와 통신하는 핵심 로직 구현
# - admin.py: 현재 비활성화
# - tests.py: 모델 및 API 엔드포인트에 대한 단위 및 통합 테스트
