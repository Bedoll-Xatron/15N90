import time
import subprocess
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AutoRunner")

def is_weekday():
    return datetime.today().weekday() < 5  # 0:Mon, 4:Fri

def run_trader():
    logger.info("=========================================")
    logger.info("자동매매 봇(mock_trader.py)을 시작합니다.")
    logger.info("=========================================")
    
    try:
        # mock_trader.py 실행 (하위 프로세스로 실행하여 끝날 때까지 대기)
        # mock_trader.py 내부 로직상 15:30에 장 마감 리포트 전송 후 스스로 종료됨
        process = subprocess.run(
            ["python", "-m", "one_candle_bot.mock_trader"], 
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        logger.info("오늘의 자동매매(mock_trader.py) 세션이 정상적으로 종료되었습니다.")
    except subprocess.CalledProcessError as e:
        logger.error(f"자동매매 봇 실행 중 오류 발생 (종료 코드: {e.returncode})")
    except Exception as e:
        logger.error(f"예기치 못한 오류: {e}")

def main():
    logger.info("24/7 무인 스케줄러(AutoRunner)가 가동되었습니다. 장 시작을 기다립니다...")
    
    while True:
        now = datetime.now()
        
        # 평일(월~금)인지 확인
        if is_weekday():
            # 오전 8시 40분 ~ 오후 3시 사이에 AutoRunner가 켜져 있으면 즉시 실행
            # (mock_trader.py 자체가 08:45 전에는 대기하고 15:30에 종료하므로 안심하고 위임)
            current_time = now.strftime("%H%M")
            if "0840" <= current_time <= "1500":
                run_trader()
                
                # mock_trader.py가 15:30에 종료된 후 여기로 돌아옴.
                # 다음 날짜까지 중복 실행되지 않도록 넉넉히 대기 (예: 다음날 아침까지)
                logger.info("오늘의 매매가 끝났습니다. 내일 아침 8시까지 휴식합니다.")
                while datetime.now().strftime("%H%M") > "1500" or datetime.now().strftime("%H%M") < "0800":
                    time.sleep(600)  # 10분 단위로 휴식
                    
        # 장 시간이 아니거나 주말이면 1분 단위로 시간 체크
        time.sleep(60)

if __name__ == "__main__":
    main()
