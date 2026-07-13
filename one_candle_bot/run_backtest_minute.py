"""
분봉 기반 백테스트 실행 스크립트

사용법:
  python run_backtest_minute.py

분봉 CSV가 없으면 진단 메시지를 출력합니다.
데이터 준비: backtest/data/README.md 참고
"""
import logging
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

from backtest.data_loader import load_stock_ohlcv, load_market_proxy
from backtest.engine import BacktestParams
from backtest.engine_minute import simulate_minute_stock
from backtest.minute_loader import available_dates
from backtest.report import BacktestReport

START  = "20230101"
END    = date.today().strftime("%Y%m%d")  # 항상 오늘까지
EQUITY = 10_000_000

TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "068270": "셀트리온",
}


def main() -> None:
    market = load_market_proxy(START, END)
    all_trades = []

    for ticker, name in TICKERS.items():
        dates = available_dates(ticker)
        if not dates:
            print(f"\n[{name}] 분봉 CSV 없음")
            print(f"  → backtest/data/{ticker}/ 폴더에 CSV 파일을 준비하세요.")
            print(f"  → 방법: backtest/data/README.md 참고")
            continue

        print(f"\n[{name}({ticker})] CSV 파일 {len(dates)}일치 발견 ({dates[0]}~{dates[-1]})")
        ohlcv  = load_stock_ohlcv(ticker, START, END)
        trades_dict = simulate_minute_stock(ticker, ohlcv, market, BacktestParams(), EQUITY)
        for strat_id, t_list in trades_dict.items():
            all_trades.extend(t_list)
        print(f"  신호 {sum(len(t) for t in trades_dict.values())}건")

    if not all_trades:
        print("\n분봉 CSV 파일이 없어 백테스트를 실행할 수 없습니다.")
        print("데이터 준비 후 재실행하세요.\n")
        return

    report = BacktestReport.from_trades(all_trades, EQUITY)
    report.print(f"원캔들 전략 — 분봉 백테스트 ({START}~{END})")


if __name__ == "__main__":
    main()
