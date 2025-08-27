# EpiLog 백엔드 부하테스트 가이드

## 🎯 개선사항

이제 **실제 PDF 파일**을 사용하여 부하테스트를 수행할 수 있습니다!

### ✨ 주요 변경사항

1. **S3 기반 PDF 통일**: 모든 환경에서 S3에서 PDF 다운로드
2. **SSE 실시간 알림**: 폴링 대신 SSE로 작업 완료 실시간 감지
3. **환경 일관성**: 개발/배포 환경에서 동일한 PDF 소스 사용
4. **Fallback 처리**: S3 다운로드 실패 시 Mock PDF 자동 생성

## 📁 PDF 파일 준비 방법 (S3 통일)

### ☁️ S3 직접 업로드 (필수) ⭐

AWS S3에 직접 테스트용 PDF를 업로드하여 로컬/배포 환경에서 동일한 파일 사용:

#### S3 업로드 방법:

1. **AWS S3 콘솔 접속**: https://s3.console.aws.amazon.com/
2. **버킷 선택**: 기존 사용 중인 S3 버킷 선택
3. **폴더 생성**: `loadtest/` 폴더 생성 (선택사항)
4. **파일 업로드**: 테스트용 PDF 파일들 업로드
5. **URL 복사**: 업로드된 각 파일의 객체 URL 복사

#### 환경변수 설정:

복사한 S3 객체 URL들을 환경변수에 설정:

```bash
# 개발환경 (.env)
LOADTEST_PDF_URLS="https://your-bucket.s3.region.amazonaws.com/loadtest/book1.pdf,https://your-bucket.s3.region.amazonaws.com/loadtest/book2.pdf"

# 배포환경 (.env.prod)
LOADTEST_PDF_URLS="https://your-bucket.s3.region.amazonaws.com/loadtest/book1.pdf,https://your-bucket.s3.region.amazonaws.com/loadtest/book2.pdf"
```

#### Docker Compose 설정:

```yaml
# docker-compose.prod.yml
environment:
  LOADTEST_PDF_URLS: "https://your-bucket.s3.region.amazonaws.com/loadtest/book1.pdf"
```

### 🔄 Mock PDF (자동 생성)

S3 다운로드 실패 시 자동으로 Mock PDF 생성

## 🚀 실행 방법

### 1. 웹 UI로 실행

```bash
cd backend_django
locust --host=http://localhost:28000
```

브라우저에서 http://localhost:8089 접속

### 2. 커맨드라인으로 실행

```bash
cd backend_django
locust --host=http://localhost:28000 --users 10 --spawn-rate 2 --run-time 60s --headless
```

## 📊 테스트 시나리오

### 사용자 타입별 비중 (2:2:6)

- **EpiLogUser (20%)**: 일반 사용자 - 전체 기능 사용
- **ReadOnlyUser (20%)**: 읽기 전용 - 조회 작업만
- **HeavyWorkloadUser (60%)**: 무거운 작업 - 생성 작업 위주

### 주요 기능 테스트

1. **회원가입/로그인**
2. **실제 PDF 책 업로드** ⭐
3. **캐릭터 생성/조회**
4. **대본 생성/조회**
5. **비동기 처리 상태 추적**

## 📈 결과 분석

### 새로운 메트릭

- **429_RATE_LIMIT**: Gemini API Rate Limit 별도 집계
- **4XX_CLIENT_ERROR**: 클라이언트 에러 상세 로깅
- **5XX_SERVER_ERROR**: 서버 에러 상세 로깅
- **E2E**: 비동기 작업 완료까지 총 소요시간

### 로그 확인

테스트 시작 시 사용될 PDF 파일 목록이 출력됩니다:

```
📋 테스트에 사용될 PDF 파일들:
  📖 sample_book.pdf (1,234,567 bytes)
  📖 example_story.pdf (987,654 bytes)
```

## ⚠️ 주의사항

1. **파일 크기**: 너무 큰 PDF는 업로드 시간이 오래 걸림
2. **저작권**: 실제 책의 저작권 확인 필요
3. **민감 정보**: 개인정보가 포함된 PDF 사용 금지
4. **백엔드 상태**: S3, Gemini API 등 외부 서비스 연결 상태 확인

## 🔧 문제 해결

### PDF 파일이 인식되지 않을 때

1. 파일 경로 확인: `backend_django/test_pdfs/`
2. 파일 권한 확인: 읽기 권한 있는지 확인
3. 파일 형식 확인: 실제 PDF 파일인지 확인

### 업로드가 실패할 때

- S3 연결 실패는 정상적인 상황으로 처리됨
- 4xx/5xx 에러는 상세 로그로 원인 파악 가능
- Gemini API Rate Limit은 별도 집계됨

---

이제 실제 책 파일로 더욱 현실적인 부하테스트를 수행할 수 있습니다! 🎉
