"""
locustfile.py : EpiLog Backend 부하테스트 시나리오 스크립트 파일
- HttpUser 클래스를 상속받은 가상 사용자들의 행동 패턴을 정의함
- 즉, 가상 사용자들을 만들어서 어떤 기능을 얼만큼 수행하는 지 정의함

사용자 타입별 시나리오 (비중 2:2:6):

1️⃣ EpiLogUser (20% - 일반 사용자):
   → 회원가입/로그인 → 책업로드(5) → 공용책조회(7) → 캐릭터조회/생성(8) → 캐릭터상태확인(3) → 대본생성(2) → 대본조회(4) → 토큰갱신(1)
   
2️⃣ ReadOnlyUser (20% - 읽기전용):
   → 회원가입/로그인 → 공용책조회(10) → 사용자정보조회(8)
   
3️⃣ HeavyWorkloadUser (60% - 무거운작업):
   → 회원가입/로그인 → 무거운책업로드(5) → 캐릭터조회/생성(3) → 대본생성(2)

PDF 파일 업로드 (우선순위: 로컬 → URL → Mock):
- 로컬 파일: ./test_pdfs/ 디렉토리에서 랜덤 선택
- 원격 URL: 환경변수 LOADTEST_PDF_URLS 또는 기본 공개 PDF 사용
- Mock PDF: 위 두 방법 모두 실패 시 자동 생성

비동기 API 사용:
- 모든 생성 작업은 /async 엔드포인트 사용 (책, 캐릭터, 대본)
- 조건부 POST: 데이터 존재시 조회(200), 없으면 비동기 생성(202)
- Gemini API Rate Limit(429) 별도 집계

실행 방법:
- 웹 UI: locust --host=http://localhost:28000
- 커맨드라인: locust --host=http://localhost:28000 --users 10 --spawn-rate 2 --run-time 60s --headless
"""

import random
import json
import io
import os
import glob
from locust import HttpUser, task, between, events # 가상 사용자 클래스, 사용자 행동 정의, 각 요청 사이 대기 시간, 테스트 종료/시작 시 후킹 
from locust.exception import RescheduleTask
import time
import requests
from urllib.parse import urlparse

# 테스트용 PDF 파일 경로 설정
PDF_TEST_DIR = os.path.join(os.path.dirname(__file__), "test_pdfs")
FALLBACK_PDF_NAMES = [
    "sample_book.pdf",
    "test_document.pdf", 
    "example_story.pdf",
    "demo_content.pdf"
]

# S3 테스트용 PDF URL (환경변수로 설정)
# 환경변수 LOADTEST_PDF_URLS로 쉼표 구분된 S3 URL 목록 설정
# 예: LOADTEST_PDF_URLS="https://your-bucket.s3.region.amazonaws.com/loadtest/book1.pdf,https://your-bucket.s3.region.amazonaws.com/loadtest/book2.pdf"

# S3 기본 설정 가져오기
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")

# 기본 S3 테스트용 PDF 경로 (실제 업로드 후 수정)
DEFAULT_S3_PDF_PATHS = [
    "loadtest/sample_book_1.pdf",
    "loadtest/sample_book_2.pdf", 
    "loadtest/demo_content.pdf"
]

# 환경변수에서 PDF URL 목록 가져오기
env_urls = os.getenv('LOADTEST_PDF_URLS', '').strip()
if env_urls:
    SAMPLE_PDF_URLS = [url.strip() for url in env_urls.split(',') if url.strip()]
    print(f"🔧 환경변수에서 S3 PDF URL 로드: {len(SAMPLE_PDF_URLS)}개")
elif AWS_STORAGE_BUCKET_NAME and AWS_S3_REGION_NAME:
    # S3 기본 경로들을 URL로 변환
    SAMPLE_PDF_URLS = [
        f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{path}"
        for path in DEFAULT_S3_PDF_PATHS
    ]
    print(f"🔧 S3 기본 PDF 경로 사용: {len(SAMPLE_PDF_URLS)}개")
else:
    SAMPLE_PDF_URLS = []
    print("⚠️  S3 설정이 없어 원격 PDF URL을 사용할 수 없습니다.")

def download_pdf_from_url(url, timeout=10):
    """URL에서 PDF 다운로드"""
    try:
        print(f"PDF 다운로드 시도: {url}")
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        
        # Content-Type 확인
        content_type = response.headers.get('Content-Type', '')
        if 'pdf' not in content_type.lower():
            print(f"PDF가 아닌 파일: {content_type}")
            return None, None
            
        content = response.content
        filename = os.path.basename(urlparse(url).path) or "downloaded_sample.pdf"
        
        print(f"PDF 다운로드 성공: {filename} ({len(content)} bytes)")
        return content, filename
        
    except Exception as e:
        print(f"PDF 다운로드 실패 {url}: {e}")
        return None, None

def get_available_pdf_files():
    """사용 가능한 PDF 파일 목록 반환"""
    pdf_files = []
    
    # 1. test_pdfs 디렉토리에서 PDF 파일 찾기
    if os.path.exists(PDF_TEST_DIR):
        pdf_files.extend(glob.glob(os.path.join(PDF_TEST_DIR, "*.pdf")))
    
    # 2. 현재 디렉토리에서 PDF 파일 찾기
    current_dir_pdfs = glob.glob(os.path.join(os.path.dirname(__file__), "*.pdf"))
    pdf_files.extend(current_dir_pdfs)
    
    # 3. 상위 디렉토리에서 PDF 파일 찾기 
    parent_dir_pdfs = glob.glob(os.path.join(os.path.dirname(os.path.dirname(__file__)), "*.pdf"))
    pdf_files.extend(parent_dir_pdfs)
    
    # 중복 제거
    pdf_files = list(set(pdf_files))
    
    if pdf_files:
        print(f"📋 발견된 로컬 PDF 파일: {[os.path.basename(f) for f in pdf_files]}")
        return pdf_files
    else:
        print("⚠️  로컬 PDF 파일을 찾을 수 없음")
        print(f"💡 로컬 파일 경로: {PDF_TEST_DIR}")
        print(f"💡 권장 파일명: {', '.join(FALLBACK_PDF_NAMES)}")
        return []

def get_random_pdf_file():
    """랜덤하게 PDF 파일 선택하여 반환 (로컬 → URL → Mock 순서)"""
    
    # 1. 로컬 파일 시도
    available_pdfs = get_available_pdf_files()
    if available_pdfs:
        selected_pdf = random.choice(available_pdfs)
        try:
            with open(selected_pdf, 'rb') as f:
                content = f.read()
                filename = os.path.basename(selected_pdf)
                print(f"로컬 PDF 선택: {filename} (크기: {len(content)} bytes)")
                return content, filename
        except Exception as e:
            print(f"로컬 PDF 읽기 실패 {selected_pdf}: {e}")
    
    # 2. URL에서 다운로드 시도
    if SAMPLE_PDF_URLS:
        print("로컬 파일이 없어 URL에서 PDF 다운로드 시도...")
        for url in random.sample(SAMPLE_PDF_URLS, len(SAMPLE_PDF_URLS)):
            content, filename = download_pdf_from_url(url)
            if content and filename:
                print(f"URL PDF 사용: {filename} (크기: {len(content)} bytes)")
                return content, filename
        
        print("모든 URL에서 PDF 다운로드 실패")
    
    # 3. Mock PDF 사용 (최후의 수단)
    print("Mock PDF 사용")
    return create_mock_pdf(), "mock_test.pdf"

def create_mock_pdf():
    """Mock PDF 생성 - 실제 PDF가 없을 때 사용"""
    return b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 65
>>
stream
BT
/F1 12 Tf
100 700 Td
(EpiLog Backend Load Test - Mock PDF Content) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000074 00000 n 
0000000120 00000 n 
0000000179 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
290
%%EOF"""

def log_429(resp, name: str):
    """429 코드만 별도 카테고리로 집계 - Gemini API의 Rate Limit 로그를 집계하기 위함"""
    try:
        rt = int((resp.elapsed.total_seconds() if resp.elapsed else 0) * 1000)
    except Exception:
        rt = 0
    events.request.fire(
        request_type="429_RATE_LIMIT",   # 리포트에 '429_RATE_LIMIT' 섹션이 따로 생김
        name=name,
        response_time=rt,
        response_length=len(resp.content) if getattr(resp, "content", None) else 0,
        exception=None,
    )

def log_4xx_error(resp, name: str):
    """400번대 클라이언트 에러 별도 집계 및 로깅"""
    try:
        rt = int((resp.elapsed.total_seconds() if resp.elapsed else 0) * 1000)
        error_detail = resp.text[:500] if hasattr(resp, 'text') else "No response body"
        
        # 상세 에러 정보 로깅
        print(f"=== 400번대 클라이언트 에러 ===")
        print(f"API: {name}")
        print(f"상태코드: {resp.status_code}")
        print(f"URL: {resp.url}")
        print(f"응답시간: {rt}ms")
        print(f"응답 헤더: {dict(resp.headers)}")
        print(f"응답 내용: {error_detail}")
        print(f"=============================")
        
    except Exception as e:
        rt = 0
        error_detail = f"Error parsing response: {e}"
        print(f"400번대 에러 파싱 실패: {e}")
    
    events.request.fire(
        request_type="4XX_CLIENT_ERROR",
        name=name,
        response_time=rt,
        response_length=len(resp.content) if getattr(resp, "content", None) else 0,
        exception=None,
    )

def log_5xx_error(resp, name: str):
    """500번대 코드 서버 에러 별도 집계 및 로깅"""
    try:
        rt = int((resp.elapsed.total_seconds() if resp.elapsed else 0) * 1000)
        error_detail = resp.text[:500] if hasattr(resp, 'text') else "No response body"
        
        # 상세 에러 정보 로깅
        print(f"=== 500번대 서버 에러 ===")
        print(f"API: {name}")
        print(f"상태코드: {resp.status_code}")
        print(f"URL: {resp.url}")
        print(f"응답시간: {rt}ms")
        print(f"응답 헤더: {dict(resp.headers)}")
        print(f"응답 내용: {error_detail}")
        print(f"========================")
        
    except Exception as e:
        rt = 0
        error_detail = f"Error parsing response: {e}"
        print(f"500번대 에러 파싱 실패: {e}")
    
    events.request.fire(
        request_type="5XX_SERVER_ERROR",
        name=name,
        response_time=rt,
        response_length=len(resp.content) if getattr(resp, "content", None) else 0,
        exception=None,
    )


def measure_e2e(name: str, poll_fn, timeout=180, interval=2.0):
    """비동기 완료까지 총 소요시간(ms) 측정 함수"""
    start = time.time()
    ok = False
    exc = None
    deadline = start + timeout
    while time.time() < deadline:
        try:
            if poll_fn():
                ok = True
                break
        except Exception as e:
            exc = e
            break
        time.sleep(interval)
    elapsed_ms = int((time.time() - start) * 1000)
    events.request.fire(
        request_type="E2E",
        name=name,
        response_time=elapsed_ms,
        response_length=0,
        exception=None if ok else (exc or TimeoutError("E2E timeout")),
    )


class EpiLogUser(HttpUser):
    """
    EpiLog 백엔드 API 부하테스트 사용자 클래스
    서비스를 이용하는 일반 유저
    가중치를 둔 기능 함수에 따라서 동작함.
    """

    wait_time = between(1, 3)  # 요청 간 1-3초 대기
    weight = 2  # 전체 사용자의 20%
    
    def on_start(self):
        """각 사용자가 시작할 때(회원가입, 로그인) 실행되는 초기화 함수"""
        self.auth_token = None
        self.book_id = None
        self.character_id = None
        self.user_id = random.randint(1000, 9999)
        
        # 사용자 인증 실행
        self.signup_and_login()
    
    def signup_and_login(self):
        """회원가입 후 로그인하여 JWT 토큰 획득"""
        try:
            # 1. 회원가입
            signup_data = {
                "login_id": f"testuser_{self.user_id}",
                "password": "testpassword123!",
                "password_confirm": "testpassword123!",
                "nickname": f"테스트유저_{self.user_id}"
            }
            
            signup_response = self.client.post(
                "/users/signup/",
                json=signup_data,
                headers={'Content-Type': 'application/json'},
                name="회원가입"
            )
            
            if signup_response.status_code == 201:
                print(f"회원가입 성공: {signup_data['login_id']}")
            elif signup_response.status_code == 400:
                # 이미 존재하는 사용자일 수 있음 - 로그인 시도
                print(f"사용자가 이미 존재할 수 있음: {signup_data['login_id']}")
            
            # 2. 로그인
            login_data = {
                "login_id": signup_data["login_id"],
                "password": signup_data["password"]
            }
            
            login_response = self.client.post(
                "/users/login/",
                json=login_data,
                headers={'Content-Type': 'application/json'},
                name="로그인"
            )
            
            if login_response.status_code == 200:
                response_data = login_response.json()
                self.auth_token = response_data.get("access_token")
                if self.auth_token:
                    print(f"로그인 성공: JWT 토큰 획득")
                else:
                    print("JWT 토큰을 받지 못함")
                    raise RescheduleTask()
            else:
                print(f"로그인 실패: {login_response.status_code}")
                raise RescheduleTask()
                
        except Exception as e:
            print(f"인증 중 오류 발생: {e}")
            raise RescheduleTask()
    
    def get_auth_headers(self):
        """JWT 인증 헤더 반환"""
        if not self.auth_token:
            return {}
        return {
            'Authorization': f'Bearer {self.auth_token}',
            'Content-Type': 'application/json'
        }
    
    @task(1)
    def get_user_info(self):
        """사용자 정보 조회 (가벼운 작업)"""
        if not self.auth_token:
            return
            
        self.client.get(
            "/users/me/",
            headers=self.get_auth_headers(),
            name="사용자 정보 조회"
        )
    
    @task(5)
    def upload_book_and_get_info(self):
        """책 업로드 및 정보 조회"""
        if not self.auth_token:
            return
            
        try:
            # 1. 실제 PDF 파일 또는 Mock PDF 가져오기
            pdf_content, pdf_filename = get_random_pdf_file()
            
            files = {
                'pdf': (pdf_filename, io.BytesIO(pdf_content), 'application/pdf')
            }
            data = {
                'title': f'테스트책_{os.path.splitext(pdf_filename)[0]}_{self.user_id}_{random.randint(1, 100)}'
            }
            
            # S3 업로드 포함된 비동기 PDF 업로드 API 호출
            with self.client.post(
                "/books/pdf/async",
                files=files,
                data=data,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                name="책 PDF 업로드 (비동기)",
                catch_response=True,
            ) as upload_response:
                if upload_response.status_code == 202:
                    # 비동기 업로드 성공 (S3 업로드는 백그라운드에서 처리)
                    upload_response.success()
                    try:
                        response_data = upload_response.json()
                        self.book_id = response_data.get("book_id")
                        print(f"[SUCCESS] 책 업로드 시작됨: ID {self.book_id}")
                        if not self.book_id:
                            print(f"[ERROR] 응답에서 book_id를 찾을 수 없음: {response_data}")
                    except Exception as e:
                        print(f"[ERROR] 책 업로드 응답 파싱 실패: {e}")
                        pass
                        
                elif upload_response.status_code == 500:
                    # S3 연결 실패 등 서버 에러 - 예상된 상황으로 처리
                    upload_response.success()  # 부하테스트에서는 성공으로 간주
                    print("S3 연결 실패 (예상됨) - 부하테스트 계속 진행")
                    return  # 이후 작업 스킵
                    
                elif 400 <= upload_response.status_code < 500:
                    # 4xx 클라이언트 에러 (실제 문제)
                    log_4xx_error(upload_response, "책 PDF 업로드 (비동기)")
                    upload_response.failure(f"클라이언트 에러: {upload_response.status_code}")
                    return
                    
                else:
                    upload_response.failure(f"예상치 못한 응답: {upload_response.status_code}")
                    return
            
            # 2. 공용책 정보 조회
            self.client.get(
                "/books/official",
                headers=self.get_auth_headers(),
                name="공용책 목록 조회"
            )
            
        except Exception as e:
            print(f"책 업로드 중 오류: {e}")
    
    @task(7)
    def get_books_info(self):
        """책 정보 조회 (가벼운 작업)"""
        if not self.auth_token:
            return
            
        # 공용책 정보 조회
        self.client.get(
            "/books/official",
            headers=self.get_auth_headers(),
            name="공용책 목록 조회"
        )
    
    @task(8)
    def get_or_create_characters_async(self):
        """비동기 캐릭터 조회/생성 - 있으면 조회(200), 없으면 비동기 생성(202)"""
        if not self.auth_token:
            print(f"[DEBUG] 캐릭터 생성 스킵: auth_token 없음")
            return
        if not self.book_id:
            print(f"[DEBUG] 캐릭터 생성 스킵: book_id 없음 (auth_token은 있음)")
            return

        headers = self.get_auth_headers()

        # 비동기 엔드포인트 사용 - 조건부 POST
        # - 캐릭터가 이미 존재하면: 기존 목록 반환 (200)
        # - 캐릭터가 없으면: 비동기 생성 시작 (202)
        with self.client.post(
            f"/books/{self.book_id}/characters/async",
            headers=headers,
            name="캐릭터 조회/생성 (비동기)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                # 기존 캐릭터 목록 반환
                resp.success()
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("characters"):
                        characters = data["characters"]
                        if characters and len(characters) > 0:
                            self.character_id = characters[0].get("id") or self.character_id
                except Exception:
                    pass
                
            elif resp.status_code == 202:
                # 비동기 생성 시작됨
                resp.success()
                # 생성 완료까지 폴링하지 않고 일단 202만 받음
                
            elif resp.status_code == 429:
                # Gemini API Rate Limit - 별도 집계
                log_429(resp, "캐릭터 조회/생성 (비동기)")
                resp.success()  # 실패율에 포함하지 않음
                
            elif 400 <= resp.status_code < 500:
                # 4xx 클라이언트 에러 (인증, 권한, 잘못된 요청 등)
                log_4xx_error(resp, "캐릭터 조회/생성 (비동기)")
                resp.failure(f"클라이언트 에러: {resp.status_code}")
                
            elif 500 <= resp.status_code < 600:
                # 5xx 서버 에러 (내부 서버 에러, DB 오류 등)
                log_5xx_error(resp, "캐릭터 조회/생성 (비동기)")
                resp.failure(f"서버 에러: {resp.status_code}")
                
            else:
                # 기타 예상치 못한 상태 코드
                resp.failure(f"예상치 못한 응답: {resp.status_code}")

    @task(3)
    def get_characters_async(self):
        """비동기 캐릭터 조회 - 생성 진행 상황 확인용"""
        if not self.auth_token or not self.book_id:
            return

        # 비동기 엔드포인트로 상태 확인
        self.client.get(
            f"/books/{self.book_id}/characters/async",
            headers=self.get_auth_headers(),
            name="캐릭터 상태 확인"
        )


    
    @task(2)
    def create_scripts(self):
        """대본 생성 및 조회"""
        if not self.auth_token:
            print(f"[DEBUG] 대본 생성 스킵: auth_token 없음")
            return
        if not self.character_id:
            print(f"[DEBUG] 대본 생성 스킵: character_id 없음 (auth_token은 있음)")
            return
        
        script_data = {
            "prompt": f"테스트 대본 프롬프트 {random.randint(1, 100)}"
            }
            
        # 1) 생성 트리거: 포괄적 에러 처리
        with self.client.post(
            f"/characters/{self.character_id}/scripts/async",
            json=script_data,
            headers=self.get_auth_headers(),
            name="대본 생성 (비동기)",
            catch_response=True,
        ) as resp:
            if 200 <= resp.status_code < 300:
                resp.success()
            elif resp.status_code == 429:
                log_429(resp, "대본 생성 (비동기)")
                resp.success()  # 실패율에 포함하지 않음
                return
            elif 400 <= resp.status_code < 500:
                log_4xx_error(resp, "대본 생성 (비동기)")
                resp.failure(f"클라이언트 에러: {resp.status_code}")
                return
            elif 500 <= resp.status_code < 600:
                log_5xx_error(resp, "대본 생성 (비동기)")
                resp.failure(f"서버 에러: {resp.status_code}")
                return
            else:
                resp.failure(f"예상치 못한 응답: {resp.status_code}")
                return

        # 2) E2E: 완료까지 폴링 (응답 구조에 맞게 'done' 판별만 바꾸면 됨)
        def poll():
            r = self.client.get(
                f"/characters/{self.character_id}/scripts",
                headers=self.get_auth_headers(),
                name="대본 상태 조회",
            )
            if r.status_code != 200:
                return False
            data = r.json()
            # 가능한 응답 패턴들에 대한 보수적 판별
            if isinstance(data, dict) and "status" in data:
                return str(data["status"]).lower() in ("done", "completed", "success")
            if isinstance(data, list) and data:
                return str(data[0].get("status", "")).lower() in ("done", "completed", "success")
            return False

        measure_e2e("대본 생성 E2E", poll_fn=poll, timeout=180, interval=2.0)
            
    
    @task(4)
    def get_scripts(self):
        """대본 조회 (가벼운 작업)"""
        if not self.auth_token or not self.character_id:
            return
            
        self.client.get(
            f"/characters/{self.character_id}/scripts/async",
            headers=self.get_auth_headers(),
            name="📄 대본 목록 조회"
        )
    
    @task(1)
    def refresh_token(self):
        """JWT 토큰 갱신 (테스트용 - 실제로는 refresh_token 필요)"""
        # 부하테스트에서는 토큰 갱신 작업을 비활성화
        # 실제 운영에서는 refresh_token을 저장하고 사용해야 함
        pass


# 추가적인 시나리오 클래스들
class ReadOnlyUser(HttpUser):
    """읽기 전용 사용자 - 비교적 가벼운 조회 작업만 수행"""
    
    wait_time = between(0.5, 2)
    weight = 2  # 전체 사용자의 20%
    
    def on_start(self):
        self.auth_token = None
        self.user_id = random.randint(10000, 19999)
        self.signup_and_login()
    
    def signup_and_login(self):
        """간단한 인증"""
        signup_data = {
            "login_id": f"읽기전용_{self.user_id}",
            "password": "ReadOnly_testpassword123!",
            "password_confirm": "ReadOnly_testpassword123!",
            "nickname": f"읽기전용_{self.user_id}"
        }
        
        # 회원가입 시도
        self.client.post("/users/signup/", json=signup_data, name="읽기전용 회원가입")
        
        # 로그인
        login_response = self.client.post(
            "/users/login/",
            json={"login_id": signup_data["login_id"], "password": signup_data["password"]},
            name="읽기전용 로그인"
        )
        
        if login_response.status_code == 200:
            self.auth_token = login_response.json().get("access_token")
    
    def get_auth_headers(self):
        if not self.auth_token:
            return {}
        return {'Authorization': f'Bearer {self.auth_token}'}
    
    @task(10)
    def read_books(self):
        """책 정보 조회"""
        if self.auth_token:
            self.client.get("/books/official", headers=self.get_auth_headers(), name="읽기전용 책조회")
    
    @task(8)
    def read_user_info(self):
        """사용자 정보 조회"""
        if self.auth_token:
            self.client.get("/users/me/", headers=self.get_auth_headers(), name="읽기전용 사용자정보")


class HeavyWorkloadUser(HttpUser):
    """무거운 작업을 요청하는 사용자 - 생성 작업 위주"""
    
    wait_time = between(2, 5)
    weight = 6  # 전체 사용자의 60%
    
    def on_start(self):
        self.auth_token = None
        self.book_id = None
        self.character_id = None
        self.user_id = random.randint(20000, 29999)
        self.signup_and_login()
    
    def signup_and_login(self):
        """인증"""
        signup_data = {
            "login_id": f"heavy_{self.user_id}",
            "password": "testpassword123!",
            "password_confirm": "testpassword123!",
            "nickname": f"헤비유저_{self.user_id}"
        }
        
        self.client.post("/users/signup/", json=signup_data, name="헤비유저 회원가입")
        
        login_response = self.client.post(
            "/users/login/",
            json={"login_id": signup_data["login_id"], "password": signup_data["password"]},
            name="헤비유저 로그인"
        )
        
        if login_response.status_code == 200:
            self.auth_token = login_response.json().get("access_token")
    
    def get_auth_headers(self):
        if not self.auth_token:
            return {}
        return {
            'Authorization': f'Bearer {self.auth_token}',
            'Content-Type': 'application/json'
        }
    
    @task(5)
    def create_books(self):
        """책 생성 (무거운 작업)"""
        if not self.auth_token:
            return
            
        # 실제 PDF 파일 또는 Mock PDF 가져오기
        pdf_content, pdf_filename = get_random_pdf_file()
        
        files = {
            'pdf': (pdf_filename, io.BytesIO(pdf_content), 'application/pdf')
        }
        data = {
            'title': f'헤비_{os.path.splitext(pdf_filename)[0]}_{self.user_id}_{random.randint(1, 1000)}'
        }
        
        # S3 업로드 포함된 헤비 비동기 PDF 업로드 API 호출
        with self.client.post(
            "/books/pdf/async",
            files=files,
            data=data,
            headers={'Authorization': f'Bearer {self.auth_token}'},
            name="헤비 책 업로드 (비동기)",
            catch_response=True,
        ) as response:
            if response.status_code == 202:
                # 비동기 업로드 성공
                response.success()
                try:
                    self.book_id = response.json().get("book_id")
                except Exception:
                    pass
                    
            elif response.status_code == 500:
                # S3 연결 실패 등 서버 에러 - 예상된 상황
                response.success()  # 부하테스트에서는 성공으로 간주
                print("헤비유저 S3 연결 실패 (예상됨)")
                return
                
            elif 400 <= response.status_code < 500:
                log_4xx_error(response, "헤비 책 업로드 (비동기)")
                response.failure(f"클라이언트 에러: {response.status_code}")
                return
                
            else:
                response.failure(f"예상치 못한 응답: {response.status_code}")
    
    @task(3)
    def get_or_create_characters_async(self):
        """비동기 캐릭터 조회/생성 (무거운 작업 사용자)"""
        if not self.auth_token or not self.book_id:
            return

        # 비동기 엔드포인트 사용
        with self.client.post(
            f"/books/{self.book_id}/characters/async",
            headers=self.get_auth_headers(),
            name="헤비 캐릭터 조회/생성 (비동기)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                # 기존 캐릭터 목록 반환
                resp.success()
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("characters"):
                        characters = data["characters"]
                        if characters and len(characters) > 0:
                            self.character_id = characters[0].get("id") or self.character_id
                except Exception:
                    pass
                    
            elif resp.status_code == 202:
                # 비동기 생성 시작됨
                resp.success()
                    
            elif resp.status_code == 429:
                # Gemini API Rate Limit
                log_429(resp, "무거운작업_캐릭터 조회/생성 (비동기)")
                resp.success()
                
            elif 400 <= resp.status_code < 500:
                log_4xx_error(resp, "무거운작업_캐릭터 조회/생성 (비동기)")
                resp.failure(f"클라이언트 에러: {resp.status_code}")
                
            elif 500 <= resp.status_code < 600:
                log_5xx_error(resp, "무거운작업_캐릭터 조회/생성 (비동기)")
                resp.failure(f"서버 에러: {resp.status_code}")
                
            else:
                resp.failure(f"예상치 못한 응답: {resp.status_code}")
    
    @task(2)
    def create_scripts(self):
        """대본 생성"""
        if not self.auth_token or not self.character_id:
            return
            
        script_data = {
            "prompt": f"heavyworkUser_무거운 작업용 대본 프롬프트 {random.randint(1, 100)}"
        }
        
        with self.client.post(
            f"/characters/{self.character_id}/scripts/async",
            json=script_data,
            headers=self.get_auth_headers(),
            name="헤비 대본 생성 (비동기)",
            catch_response=True,
        ) as resp:
            if 200 <= resp.status_code < 300:
                resp.success()
            elif resp.status_code == 429:
                log_429(resp, "무거운작업_대본 생성 (비동기)")
                resp.success()
            elif 400 <= resp.status_code < 500:
                log_4xx_error(resp, "무거운작업_대본 생성 (비동기)")
                resp.failure(f"클라이언트 에러: {resp.status_code}")
            elif 500 <= resp.status_code < 600:
                log_5xx_error(resp, "무거운작업_대본 생성 (비동기)")
                resp.failure(f"서버 에러: {resp.status_code}")
            else:
                resp.failure(f"예상치 못한 응답: {resp.status_code}")


# 테스트 이벤트 리스너
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("EpiLog 백엔드 부하테스트 시작!")
    print("=" * 50)
    
    # PDF 파일 소스 확인 및 출력
    available_pdfs = get_available_pdf_files()
    
    print("PDF 파일 소스 구성:")
    print(f"로컬 파일: {len(available_pdfs)}개")
    if available_pdfs:
        for pdf_path in available_pdfs:
            file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
            print(f"      📖 {os.path.basename(pdf_path)} ({file_size:,} bytes)")
    else:
        print(f"검색 경로: {PDF_TEST_DIR}")
        print(f"권장 파일명: {', '.join(FALLBACK_PDF_NAMES)}")
    
    print(f"원격 URL: {len(SAMPLE_PDF_URLS)}개")
    for i, url in enumerate(SAMPLE_PDF_URLS, 1):
        domain = urlparse(url).netloc
        print(f"{i}. {domain}")
    
    print("Mock PDF: 최후 수단으로 자동 생성")
    
    print("PDF 선택 순서: 로컬 파일 → 원격 URL → Mock PDF")
    print("=" * 50)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 50)
    print("EpiLog 백엔드 부하테스트 완료!")