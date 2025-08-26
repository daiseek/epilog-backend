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
from locust import HttpUser, task, between, events # 가상 사용자 클래스, 사용자 행동 정의, 각 요청 사이 대기 시간, 테스트 종료/시작 시 후킹 
from locust.exception import RescheduleTask
import time

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
        error_detail = resp.text[:200] if hasattr(resp, 'text') else "No response body"
    except Exception:
        rt = 0
        error_detail = "Error parsing response"
    
    print(f"400번대 코드 클라이언트 에러 - {name}: {resp.status_code} | {error_detail}")
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
        error_detail = resp.text[:200] if hasattr(resp, 'text') else "No response body"
    except Exception:
        rt = 0
        error_detail = "Error parsing response"
    
    print(f"500번대 서버 에러 - {name}: {resp.status_code} | {error_detail}")
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
            # 1. 책 PDF 업로드 (mock 파일)
            # 실제 PDF 파일 대신 텍스트 파일 업로드
            mock_pdf_content = f"Mock PDF : {self.user_id}_{random.randint(1, 100)}"
            files = {
                'pdf_file': ('test_book.pdf', io.BytesIO(mock_pdf_content.encode()), 'application/pdf')
            }
            data = {
                'title': f'테스트 책 {self.user_id}_{random.randint(1, 100)}'
            }
            
            upload_response = self.client.post(
                "/books/pdf",
                files=files,
                data=data,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                name="📚 책 PDF 업로드"
            )
            
            if upload_response.status_code == 201:
                response_data = upload_response.json()
                self.book_id = response_data.get("id")
                print(f"책 업로드 성공: ID {self.book_id}")
            else:
                print(f"책 업로드 실패: {upload_response.status_code}")
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
        if not self.auth_token or not self.book_id:
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
        if not self.auth_token or not self.character_id:
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
        """JWT 토큰 갱신"""
        if not self.auth_token:
            return
            
        # 실제로는 refresh_token이 필요하지만, 여기서는 단순화
        self.client.post(
            "/users/token/refresh/",
            headers=self.get_auth_headers(),
            name="토큰 갱신"
        )


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
            
        mock_content = f"Heavy work - generate book {random.randint(1, 1000)}"
        files = {
            'pdf_file': ('heavy_book.pdf', io.BytesIO(mock_content.encode()), 'application/pdf')
        }
        data = {
            'title': f'무거운작업책 {random.randint(1, 1000)}'
        }
        
        response = self.client.post(
            "/books/pdf/async",
            files=files,
            data=data,
            headers={'Authorization': f'Bearer {self.auth_token}'},
            name="헤비 책 업로드 (비동기)"
        )
        
        if response.status_code == 201:
            self.book_id = response.json().get("id")
    
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


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 50)
    print("EpiLog 백엔드 부하테스트 완료!")