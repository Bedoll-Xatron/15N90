@echo off
chcp 65001 >nul
echo =========================================
echo 원캔들 모의투자 봇 자동 실행 스크립트
echo 실행 시간: %date% %time%
echo =========================================

cd /d "D:\Project2026\15N90\one_candle_bot"

:: 기존 프로세스가 남아 있을 경우 정리 후 재시작
pm2 delete one_candle_mock 2>nul
echo [PM2] 기존 프로세스 정리 완료

pm2 start mock_trader.py --interpreter python --name "one_candle_mock" --no-autorestart
echo [PM2] 새 프로세스 시작 완료
pm2 save

echo.
echo =========================================
echo 봇이 백그라운드에서 실행 중입니다.
echo 로그 확인: pm2 logs one_candle_mock
echo =========================================
