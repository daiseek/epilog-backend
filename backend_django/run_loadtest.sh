#!/bin/bash

# EpiLog 백엔드 부하테스트 실행 스크립트

echo "--EpiLog 백엔드 부하테스트 시작!--"
echo "=" * 50

# 리포트 디렉토리 생성
mkdir -p reports

# 서버 상태 확인
echo "서버 상태 확인 중..."
if curl -s http://localhost:28000/ > /dev/null; then
    echo "서버가 실행 중입니다."
else
    echo "서버가 실행되지 않았습니다. Django 서버를 먼저 시작해주세요."
    echo "   python manage.py runserver 0.0.0.0:28000"
    exit 1
fi

# 사용자에게 실행 모드 선택 제공
echo ""
echo "부하테스트 실행 모드를 선택하세요:"
echo "1) 웹 UI 모드 (추천) - 브라우저에서 테스트 설정"
echo "2) 경량 테스트 (10 사용자, 1분)"
echo "3) 중간 부하 테스트 (50 사용자, 5분)"
echo "4) 고부하 테스트 (100 사용자, 10분)"
echo "5) 사용자 정의 설정"

read -p "선택하세요 (1-5): " choice

case $choice in
    1)
        echo "웹 UI 모드로 실행 중..."
        echo "브라우저에서 http://localhost:8089 접속하세요"
        locust --config=locust.conf
        ;;
    2)
        echo "경량 테스트 실행 중..."
        locust --config=locust.conf --headless --users 10 --spawn-rate 2 --run-time 60s
        ;;
    3)
        echo "중간 부하 테스트 실행 중..."
        locust --config=locust.conf --headless --users 50 --spawn-rate 5 --run-time 300s
        ;;
    4)
        echo "고부하 테스트 실행 중..."
        locust --config=locust.conf --headless --users 100 --spawn-rate 10 --run-time 600s
        ;;
    5)
        read -p "사용자 수: " users
        read -p "초당 생성 사용자 수: " spawn_rate
        read -p "실행 시간 (초): " run_time
        echo "사용자 정의 테스트 실행 중..."
        locust --config=locust.conf --headless --users $users --spawn-rate $spawn_rate --run-time ${run_time}s
        ;;
    *)
        echo "잘못된 선택입니다."
        exit 1
        ;;
esac

echo ""
echo "테스트 결과는 reports/ 폴더에 저장:"
echo "  - HTML 리포트: reports/locust_report.html"
echo "  - CSV 결과: reports/locust_results_*.csv"
echo "  - 로그 파일: locust.log"
echo ""
echo "부하테스트 완료"
