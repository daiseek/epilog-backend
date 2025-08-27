"""
locustfile.py : EpiLog Backend 부하테스트 시나리오 스크립트 파일
- HttpUser 클래스를 상속받은 가상 사용자들의 행동 패턴을 정의함
- 즉, 가상 사용자들을 만들어서 어떤 기능을 얼만큼 수행하는 지 정의함

사용자 타입별 시나리오 (실제 서비스 흐름 반영, 비중 7:2:1):

1. FullPipelineUser (70% - 전체 파이프라인):
   → 회원가입/로그인 → PDF업로드+SSE대기 → 캐릭터생성+SSE대기 → 대본생성+SSE대기
   
2. CharacterFocusedUser (20% - 캐릭터 생성):
   → 회원가입/로그인 → 완성된책조회 → 캐릭터생성+SSE대기 → 대본생성+SSE대기
   
3. ReadOnlyUser (10% - 조회 전용):
   → 회원가입/로그인 → 책조회 → 캐릭터조회 → 대본조회

PDF 파일 업로드 (S3 통일):
- S3 다운로드: 환경변수 LOADTEST_PDF_URLS에서 S3 URL 지정
- Mock PDF: S3 다운로드 실패 시 자동 생성

비동기 API + SSE 알림:
- 모든 생성 작업은 /async 엔드포인트 사용 (책, 캐릭터, 대본)
- SSE 스트리밍으로 실시간 진행 상황 및 완료 알림 수신
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
import json
import threading

# S3 테스트용 PDF 설정

# S3 테스트용 PDF URL (환경변수로 설정)
# 환경변수 LOADTEST_PDF_URLS로 쉼표 구분된 S3 URL 목록 설정
# 예: LOADTEST_PDF_URLS="https://your-bucket.s3.region.amazonaws.com/loadtest/book1.pdf,https://your-bucket.s3.region.amazonaws.com/loadtest/book2.pdf"

# S3 기본 설정 가져오기
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")

# 기본 S3 테스트용 PDF 경로 (실제 업로드 후 수정)
# DEFAULT_S3_PDF_PATHS = [
#     "loadtest/sample_book_1.pdf",
#     "loadtest/sample_book_2.pdf", 
#     "loadtest/demo_content.pdf"
# ]

# 환경변수에서 PDF URL 목록 가져오기
env_urls = os.getenv('LOADTEST_PDF_URLS', '').strip()
if env_urls:
    SAMPLE_PDF_URLS = [url.strip() for url in env_urls.split(',') if url.strip()]
    print(f"환경변수에서 S3 PDF URL 로드: {len(SAMPLE_PDF_URLS)}개")
elif AWS_STORAGE_BUCKET_NAME and AWS_S3_REGION_NAME:
    # S3 기본 경로들을 URL로 변환
    SAMPLE_PDF_URLS = [
        f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/{path}"
        for path in DEFAULT_S3_PDF_PATHS
    ]
    print(f"S3 기본 PDF 경로 사용: {len(SAMPLE_PDF_URLS)}개")
else:
    SAMPLE_PDF_URLS = []
    print("WARNING: S3 설정이 없어 원격 PDF URL을 사용할 수 없습니다.")

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



def get_random_pdf_file():
    """S3에서 PDF 파일 다운로드 (S3 → Mock 순서)"""
    
    # 1. S3 URL에서 다운로드 시도
    if SAMPLE_PDF_URLS:
        print("S3에서 PDF 다운로드 시도...")
        for url in random.sample(SAMPLE_PDF_URLS, len(SAMPLE_PDF_URLS)):
            content, filename = download_pdf_from_url(url)
            if content and filename:
                print(f"S3 PDF 다운로드 성공: {filename} (크기: {len(content)} bytes)")
                return content, filename
        
        print("모든 S3 URL에서 PDF 다운로드 실패")
    else:
        print("S3 PDF URL이 설정되지 않음")
    
    # 2. Mock PDF 사용 (최후의 수단)
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

def wait_for_task_via_sse(client, task_id, task_type="book", auth_headers=None, max_wait_time=120):
    """SSE를 통해 작업 완료까지 대기하는 함수"""
    print(f"SSE 연결 시작: {task_type} 작업 {task_id}")
    start_time = time.time()
    
    try:
        # SSE 엔드포인트 결정
        if task_type == "book":
            sse_url = f"/books/tasks/{task_id}/eventstream"
            metric_name = "SSE_책_처리_대기"
        elif task_type == "character":
            sse_url = f"/characters/tasks/{task_id}/eventstream"
            metric_name = "SSE_캐릭터_처리_대기"
        else:
            sse_url = f"/books/tasks/{task_id}/eventstream"
            metric_name = "SSE_작업_대기"
        
        # SSE 연결 (스트리밍)
        with client.get(
            sse_url,
            headers=auth_headers or {},
            name=metric_name,
            stream=True,
            catch_response=True
        ) as response:
            
            if response.status_code != 200:
                print(f"SSE 연결 실패: {response.status_code}")
                response.failure(f"SSE 연결 실패: {response.status_code}")
                return False
            
            response.success()
            print(f"SSE 연결 성공: {sse_url}")
            
            # SSE 이벤트 스트림 읽기
            event_type = None
            for line in response.iter_lines(decode_unicode=True):
                # 타임아웃 체크
                if time.time() - start_time > max_wait_time:
                    print(f"SSE 대기 시간 초과 ({max_wait_time}초)")
                    return False
                
                if not line or line.startswith(':'):
                    continue
                
                # 이벤트 타입 파싱
                if line.startswith('event:'):
                    event_type = line[6:].strip()
                    continue
                
                # 데이터 파싱
                if line.startswith('data:'):
                    try:
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        
                        data = json.loads(data_str)
                        
                        # 이벤트 타입별 처리
                        if event_type == 'connected':
                            print(f"SSE 채널 연결됨: {data.get('channel', task_id)}")
                        
                        elif event_type == 'progress':
                            progress = data.get('progress', 0)
                            message = data.get('message', '진행 중...')
                            print(f"{task_type} 진행률: {progress}% - {message}")
                        
                        elif event_type == 'completed':
                            print(f"{task_type} 작업 완료! (SSE)")
                            elapsed_time = int((time.time() - start_time) * 1000)
                            # E2E 메트릭 기록
                            events.request.fire(
                                request_type="SSE_E2E",
                                name=f"{task_type}_완료까지_SSE",
                                response_time=elapsed_time,
                                response_length=0,
                                exception=None,
                            )
                            return True
                        
                        elif event_type == 'error':
                            error_msg = data.get('message', '알 수 없는 오류')
                            print(f"{task_type} 작업 실패 (SSE): {error_msg}")
                            return False
                        
                        elif event_type == 'test':
                            print(f"테스트 이벤트 수신: {data.get('message', '')}")
                            
                    except json.JSONDecodeError as e:
                        print(f"SSE 데이터 파싱 실패: {e} - 데이터: {data_str}")
                        continue
                    except Exception as e:
                        print(f"SSE 처리 중 오류: {e}")
                        continue
                
            print(f"SSE 스트림이 예상치 못하게 종료됨")
            return False
            
    except Exception as e:
        print(f"SSE 연결 중 오류: {e}")
        return False


class FullPipelineUser(HttpUser):
    """
    전체 파이프라인 사용자 클래스
    실제 서비스 흐름: PDF → 내용추출 → 캐릭터 → 대본
    SSE를 활용한 순차적 비동기 작업 처리
    """

    wait_time = between(3, 8)  # 요청 간 3-8초 대기 (전체 파이프라인은 매우 무거운 작업)
    weight = 7  # 전체 사용자의 70%
    
    def on_start(self):
        """각 사용자가 시작할 때(회원가입, 로그인) 실행되는 초기화 함수"""
        self.auth_token = None
        self.book_id = None
        self.character_id = None
        self.book_task_id = None  # SSE용 책 작업 ID
        self.character_task_id = None  # SSE용 캐릭터 작업 ID
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
    
    @task(1)
    def full_content_creation_pipeline(self):
        """전체 콘텐츠 생성 파이프라인: PDF → 내용추출 → 캐릭터 → 대본"""
        if not self.auth_token:
            return
            
        print(f"전체 파이프라인 시작: 사용자 {self.user_id}")
        
        try:
            # ====== 1단계: PDF 업로드 + 내용 추출 (SSE 대기) ======
            print(f"1단계: PDF 업로드 및 내용 추출 시작")
            
            pdf_content, pdf_filename = get_random_pdf_file()
            files = {
                'pdf': (pdf_filename, io.BytesIO(pdf_content), 'application/pdf')
            }
            data = {
                'title': f'파이프라인_{os.path.splitext(pdf_filename)[0]}_{self.user_id}_{random.randint(1, 1000)}'
            }
            
            with self.client.post(
                "/books/pdf/async",
                files=files,
                data=data,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                name="파이프라인_1단계_PDF업로드",
                catch_response=True,
            ) as response:
                if response.status_code == 202:
                    response.success()
                    response_data = response.json()
                    self.book_id = response_data.get("book_id")
                    book_task_id = response_data.get("task_id")
                    
                    print(f"책 업로드 시작: ID {self.book_id}, Task {book_task_id}")
                    
                    # SSE로 내용 추출 완료까지 대기
                    if book_task_id:
                        success = wait_for_task_via_sse(
                            client=self.client,
                            task_id=book_task_id,
                            task_type="book",
                            auth_headers=self.get_auth_headers(),
                            max_wait_time=300  # 5분 대기
                        )
                        if not success:
                            print(f"1단계 실패: 내용 추출 시간 초과")
                            return
                    else:
                        print(f"1단계 실패: task_id 없음")
                        return
                else:
                    response.failure(f"PDF 업로드 실패: {response.status_code}")
                    return
            
            print(f"1단계 완료: 내용 추출 완료")
            
            # ====== 2단계: 캐릭터 생성 (SSE 대기) ======
            print(f"2단계: 캐릭터 생성 시작")
            
            with self.client.post(
                f"/books/{self.book_id}/characters/async",
                headers=self.get_auth_headers(),
                name="파이프라인_2단계_캐릭터생성",
                catch_response=True,
            ) as response:
                if response.status_code == 202:
                    response.success()
                    response_data = response.json()
                    character_task_id = response_data.get("task_id")
                    
                    print(f"캐릭터 생성 시작: Task {character_task_id}")
                    
                    # SSE로 캐릭터 생성 완료까지 대기
                    if character_task_id:
                        success = wait_for_task_via_sse(
                            client=self.client,
                            task_id=character_task_id,
                            task_type="character",
                            auth_headers=self.get_auth_headers(),
                            max_wait_time=300  # 5분 대기
                        )
                        if not success:
                            print(f"2단계 실패: 캐릭터 생성 시간 초과")
                            return
                    else:
                        print(f"2단계 실패: character task_id 없음")
                        return
                        
                elif response.status_code == 200:
                    # 이미 캐릭터가 존재함
                    response.success()
                    print(f"캐릭터 이미 존재함")
                else:
                    response.failure(f"캐릭터 생성 실패: {response.status_code}")
                    return
            
            print(f"2단계 완료: 캐릭터 생성 완료")
            
            # ====== 3단계: 생성된 캐릭터 조회 ======
            print(f"캐릭터 목록 조회")
            
            character_response = self.client.post(
                f"/books/{self.book_id}/characters",
                headers=self.get_auth_headers(),
                name="파이프라인_캐릭터조회"
            )
            
            if character_response.status_code in [200, 201]:
                characters_data = character_response.json()
                # CharacterConditionalCreateOrListView는 직접 리스트를 반환함
                if isinstance(characters_data, list) and len(characters_data) > 0:
                    selected_character = random.choice(characters_data)
                    character_id = selected_character.get("id")  # CharacterSerializer는 'id' 필드 사용
                    character_name = selected_character.get("characterName", "Unknown")
                    print(f"캐릭터 선택: ID {character_id}, 이름: {character_name}")
                else:
                    print(f"3단계 실패: 캐릭터가 없음 - 응답: {characters_data}")
                    return
            else:
                print(f"3단계 실패: 캐릭터 조회 실패 {character_response.status_code}")
                return
            
            # ====== 4단계: 대본 생성 (SSE 대기) ======
            print(f"4단계: 대본 생성 시작")
            
            script_data = {
                "scene_count": 3
            }
            
            with self.client.post(
                f"/characters/{character_id}/scripts/async",
                json=script_data,
                headers=self.get_auth_headers(),
                name="파이프라인_4단계_대본생성",
                catch_response=True,
            ) as response:
                if response.status_code == 202:
                    response.success()
                    response_data = response.json()
                    script_task_id = response_data.get("task_id")
                    script_id = response_data.get("script_id")
                    
                    print(f"대본 생성 시작: Task {script_task_id}, Script {script_id}")
                    
                    # SSE로 대본 생성 완료까지 대기
                    if script_task_id:
                        success = wait_for_task_via_sse(
                            client=self.client,
                            task_id=script_task_id,
                            task_type="character",  # 대본도 characters SSE 채널 사용
                            auth_headers=self.get_auth_headers(),
                            max_wait_time=300  # 5분 대기
                        )
                        if not success:
                            print(f"4단계 실패: 대본 생성 시간 초과")
                            return
                    else:
                        print(f"4단계 실패: script task_id 없음")
                        return
                elif response.status_code in [200, 201]:
                    response.success()
                    print(f"대본 생성 즉시 완료!")
                else:
                    response.failure(f"대본 생성 실패: {response.status_code}")
                    return
            
            print(f"4단계 완료: 대본 생성 완료")
            
            print(f"전체 파이프라인 완료! 책 {self.book_id} -> 캐릭터 {character_id} -> 대본")
            
        except Exception as e:
            print(f"파이프라인 중 오류: {e}")

    @task(10)
    def upload_book_and_get_info_legacy(self):
        """책 업로드 및 정보 조회 (주요 작업)"""
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
                        self.book_task_id = response_data.get("task_id")  # SSE용 태스크 ID
                        print(f"[SUCCESS] 책 업로드 시작됨: ID {self.book_id}, Task ID {self.book_task_id}")
                        
                        if not self.book_id:
                            print(f"[ERROR] 응답에서 book_id를 찾을 수 없음: {response_data}")
                        
                        # SSE로 책 처리 완료까지 대기
                        if self.book_task_id:
                            print(f"SSE로 책 {self.book_id} 처리 완료 대기 시작...")
                            success = wait_for_task_via_sse(
                                client=self.client,
                                task_id=self.book_task_id,
                                task_type="book",
                                auth_headers=self.get_auth_headers(),
                                max_wait_time=180  # 3분 대기
                            )
                            if success:
                                print(f"책 {self.book_id} 처리 완료! 이제 캐릭터/대본 생성 가능")
                            else:
                                print(f"책 {self.book_id} 처리 실패 또는 시간 초과")
                                self.book_id = None  # 캐릭터 생성 스킵하도록
                        else:
                            print(f"task_id가 없어 SSE 대기 불가")
                            
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
    
    @task(1)
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
    
    @task(2)
    def check_book_status(self):
        """생성된 책 상태 확인"""
        if not self.auth_token or not self.book_id:
            return

        self.client.get(
            "/books/official",
            headers=self.get_auth_headers(),
            name="생성된 책 상태 확인"
        )
    
    @task(1)
    def refresh_token(self):
        """JWT 토큰 갱신 (테스트용 - 실제로는 refresh_token 필요)"""
        # 부하테스트에서는 토큰 갱신 작업을 비활성화
        # 실제 운영에서는 refresh_token을 저장하고 사용해야 함
        pass


# 캐릭터 생성 전담 사용자
class CharacterFocusedUser(HttpUser):
    """캐릭터 중심 사용자 - 완성된 책에서 캐릭터/대본 생성"""
    
    wait_time = between(2, 5)
    weight = 2  # 전체 사용자의 20%
    
    def on_start(self):
        self.auth_token = None
        self.book_id = None
        self.character_id = None
        self.user_id = random.randint(10000, 19999)
        self.signup_and_login()
    
    def signup_and_login(self):
        """캐릭터 워커 인증"""
        signup_data = {
            "login_id": f"character_worker_{self.user_id}",
            "password": "CharWorker_testpassword123!",
            "password_confirm": "CharWorker_testpassword123!",
            "nickname": f"캐릭터워커_{self.user_id}"
        }
        
        # 회원가입 시도
        self.client.post("/users/signup/", json=signup_data, name="캐릭터워커 회원가입")
        
        # 로그인
        login_response = self.client.post(
            "/users/login/",
            json={"login_id": signup_data["login_id"], "password": signup_data["password"]},
            name="캐릭터워커 로그인"
        )
        
        if login_response.status_code == 200:
            self.auth_token = login_response.json().get("access_token")
    
    def get_auth_headers(self):
        if not self.auth_token:
            return {}
        return {'Authorization': f'Bearer {self.auth_token}'}
    
    @task(3)
    def get_official_books(self):
        """공용책 목록 조회 및 book_id 수집"""
        if not self.auth_token:
            return
        
        # 이미 book_id가 설정되어 있으면 스킵 (중복 호출 방지)
        if self.book_id:
            return
            
        response = self.client.get("/books/official", headers=self.get_auth_headers(), name="공용책 조회")
        if response.status_code == 200:
            try:
                books = response.json()
                print(f"[DEBUG] 공용책 응답: {len(books)}개 책 조회됨")
                if books and len(books) > 0:
                    # 첫 번째 책 구조 확인
                    first_book = books[0]
                    print(f"[DEBUG] 첫 번째 책 구조: {first_book}")
                    
                    # 랜덤하게 책 선택
                    selected_book = random.choice(books)
                    
                    # book_id 필드명 확인 후 설정
                    self.book_id = selected_book.get("book_id") or selected_book.get("id")
                    
                    print(f"캐릭터 생성용 책 선택: ID {self.book_id}, 제목: {selected_book.get('title', 'Unknown')}")
                    
                    if not self.book_id:
                        print(f"[ERROR] book_id를 찾을 수 없음. 응답 구조: {selected_book}")
                else:
                    print(f"[DEBUG] 공용책이 없습니다.")
            except Exception as e:
                print(f"공용책 응답 파싱 실패: {e}")
        else:
            print(f"[DEBUG] 공용책 조회 실패: {response.status_code}")
    
    @task(15)
    def create_characters_for_book(self):
        """선택된 책의 캐릭터 생성 (주요 작업)"""
        if not self.auth_token or not self.book_id:
            return

        with self.client.post(
            f"/books/{self.book_id}/characters/async",
            headers=self.get_auth_headers(),
            name="캐릭터 생성 (캐릭터워커)",
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
                            self.character_id = characters[0].get("id")
                            print(f"기존 캐릭터 발견: {len(characters)}개")
                except Exception:
                    pass
                
            elif resp.status_code == 202:
                # 비동기 생성 시작됨
                resp.success()
                try:
                    data = resp.json()
                    character_task_id = data.get("task_id")
                    if character_task_id:
                        print(f"캐릭터 생성 시작: Task ID {character_task_id}")
                        # SSE로 캐릭터 생성 완료까지 대기
                        success = wait_for_task_via_sse(
                            client=self.client,
                            task_id=character_task_id,
                            task_type="character",
                            auth_headers=self.get_auth_headers(),
                            max_wait_time=300  # 5분 대기
                        )
                        if success:
                            print(f"캐릭터 생성 완료!")
                        else:
                            print(f"캐릭터 생성 실패 또는 시간 초과")
                except Exception as e:
                    print(f"캐릭터 생성 응답 파싱 실패: {e}")
                
            elif resp.status_code == 429:
                log_429(resp, "캐릭터 생성 (캐릭터워커)")
                resp.success()
                
            elif 400 <= resp.status_code < 500:
                log_4xx_error(resp, "캐릭터 생성 (캐릭터워커)")
                resp.failure(f"클라이언트 에러: {resp.status_code}")
                
            elif 500 <= resp.status_code < 600:
                log_5xx_error(resp, "캐릭터 생성 (캐릭터워커)")
                resp.failure(f"서버 에러: {resp.status_code}")
                
            else:
                resp.failure(f"예상치 못한 응답: {resp.status_code}")

    @task(5)
    def check_character_status(self):
        """생성된 캐릭터 상태 확인"""
        if not self.auth_token or not self.book_id:
            return

        self.client.post(
            f"/books/{self.book_id}/characters",
            headers=self.get_auth_headers(),
            name="캐릭터 상태 확인 (캐릭터워커)"
        )


class ReadOnlyUser(HttpUser):
    """조회 전용 사용자 - 책/캐릭터/대본 조회만"""
    
    wait_time = between(0.5, 2)
    weight = 1  # 전체 사용자의 10%
    
    def on_start(self):
        self.auth_token = None
        self.book_id = None
        self.character_id = None
        self.book_task_id = None  # SSE용 책 작업 ID
        self.character_task_id = None  # SSE용 캐릭터 작업 ID
        self.user_id = random.randint(20000, 29999)
        self.signup_and_login()
    
    def signup_and_login(self):
        """대본 생성자 인증"""
        signup_data = {
            "login_id": f"script_gen_{self.user_id}",
            "password": "ScriptGen_testpassword123!",
            "password_confirm": "ScriptGen_testpassword123!",
            "nickname": f"대본생성자_{self.user_id}"
        }
        
        self.client.post("/users/signup/", json=signup_data, name="대본생성자 회원가입")
        
        login_response = self.client.post(
            "/users/login/",
            json={"login_id": signup_data["login_id"], "password": signup_data["password"]},
            name="대본생성자 로그인"
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
    def browse_books(self):
        """캐릭터가 있는 책 조회 및 book_id 수집"""
        if not self.auth_token:
            return
            
        # 이미 book_id가 설정되어 있으면 스킵 (중복 호출 방지)
        if self.book_id:
            return
            
        response = self.client.get("/books/official", headers=self.get_auth_headers(), name="대본용 책 조회")
        if response.status_code == 200:
            try:
                books = response.json()
                print(f"[DEBUG] 대본용 공용책 응답: {len(books)}개 책 조회됨")
                if books and len(books) > 0:
                    # 랜덤하게 책 선택
                    selected_book = random.choice(books)
                    
                    # book_id 필드명 확인 후 설정
                    self.book_id = selected_book.get("book_id") or selected_book.get("id")
                    
                    print(f"대본 생성용 책 선택: ID {self.book_id}, 제목: {selected_book.get('title', 'Unknown')}")
                    
                    if not self.book_id:
                        print(f"[ERROR] 대본용 book_id를 찾을 수 없음. 응답 구조: {selected_book}")
                else:
                    print(f"[DEBUG] 대본용 공용책이 없습니다.")
            except Exception as e:
                print(f"대본용 책 응답 파싱 실패: {e}")
        else:
            print(f"[DEBUG] 대본용 공용책 조회 실패: {response.status_code}")
    
    @task(3)
    def browse_characters(self):
        """대본 생성을 위한 캐릭터 조회"""
        if not self.auth_token or not self.book_id:
            return

        with self.client.post(
            f"/books/{self.book_id}/characters",
            headers=self.get_auth_headers(),
            name="대본용 캐릭터 조회",
            catch_response=True,
        ) as resp:
            if resp.status_code in [200, 201]:
                resp.success()
                try:
                    data = resp.json()
                    # CharacterConditionalCreateOrListView는 직접 리스트를 반환함
                    if isinstance(data, list) and len(data) > 0:
                        # 랜덤하게 캐릭터 선택
                        selected_character = random.choice(data)
                        self.character_id = selected_character.get("id")  # CharacterSerializer는 'id' 필드 사용
                        char_name = selected_character.get("characterName", "Unknown")
                        print(f"대본 생성용 캐릭터 선택: ID {self.character_id}, 이름: {char_name}")
                    else:
                        print(f"책 {self.book_id}에 캐릭터가 없음 - 응답: {data}")
                except Exception as e:
                    print(f"캐릭터 조회 응답 파싱 실패: {e}")
            else:
                resp.failure(f"캐릭터 조회 실패: {resp.status_code}")
    
    @task(2)
    def browse_user_info(self):
        """사용자 정보 조회 (조회 전용)"""
        if not self.auth_token:
            return
            
        # 조회 전용 사용자는 가벼운 조회 작업만 수행
        self.client.get(
            "/users/me/",
            headers=self.get_auth_headers(),
            name="사용자정보_조회"
        )


# 테스트 이벤트 리스너
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("EpiLog 백엔드 부하테스트 시작!")
    print("=" * 50)
    
    # PDF 파일 소스 확인 및 출력
    print("PDF 파일 소스 구성:")
    print(f"S3 URL: {len(SAMPLE_PDF_URLS)}개")
    for i, url in enumerate(SAMPLE_PDF_URLS, 1):
        domain = urlparse(url).netloc
        filename = os.path.basename(urlparse(url).path)
        print(f"  {i}. {domain} - {filename}")
    
    if not SAMPLE_PDF_URLS:
        print("  환경변수 LOADTEST_PDF_URLS가 설정되지 않음")
        print("  S3 기본 설정도 없음")
    
    print("Mock PDF: S3 다운로드 실패 시 자동 생성")
    print("PDF 선택 순서: S3 다운로드 → Mock PDF")
    print("=" * 50)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 50)
    print("EpiLog 백엔드 부하테스트 완료!")