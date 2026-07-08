"""
백테스트 실행 스크립트

사용법:
  python run_backtest.py               # 기본 종목, 기본 파라미터
  python run_backtest.py --optimize    # Grid Search 파라미터 최적화

⚠ 일봉 근사 백테스트입니다.
  전일 고/저가를 15분봉 박스로, 당일 일봉 패턴을 반전 신호로 근사합니다.
  실제 분봉 전략의 정확한 성과와 다를 수 있습니다.
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 기본 설정
START  = "20230101"
END    = "20241231"
EQUITY = 10_000_000

TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "068270": "셀트리온",
}


def run_single(args) -> None:
    from backtest.data_loader import load_stock_ohlcv, load_market_proxy
    from backtest.engine import BacktestParams, simulate_one_stock
    from backtest.report import BacktestReport

    logger.info(f"기간: {START} ~ {END}  초기자산: {EQUITY:,}원")
    market = load_market_proxy(START, END)

    all_trades = []
    for ticker, name in TICKERS.items():
        ohlcv = load_stock_ohlcv(ticker, START, END)
        if ohlcv.empty:
            logger.warning(f"{name}({ticker}) 데이터 없음")
            continue
        trades = simulate_one_stock(ohlcv, market, ticker, BacktestParams(), EQUITY)
        logger.info(f"  {name}: {len(trades)}건")
        all_trades.extend(trades)

    report = BacktestReport.from_trades(all_trades, EQUITY)
    report.print(f"원캔들 전략 — 일봉 근사 ({START}~{END})")


def run_optimize(args) -> None:
    from backtest.data_loader import load_stock_ohlcv, load_market_proxy
    from backtest.optimizer import optimize, print_top_results

    logger.info("Grid Search 최적화 시작...")
    market = load_market_proxy(START, END)

    stock_data = {}
    for ticker, name in TICKERS.items():
        ohlcv = load_stock_ohlcv(ticker, START, END)
        if not ohlcv.empty:
            stock_data[ticker] = ohlcv
            logger.info(f"  로드 완료: {name}({ticker})  {len(ohlcv)}일")

    results = optimize(stock_data, market, initial_equity=EQUITY)

    if not results:
        print("유효한 결과 없음 (거래 횟수 부족)")
        return

    print_top_results(results, top_n=5)

    best = results[0]
    print(f"\n최적 파라미터:")
    print(f"  atr_ratio   = {best.params.atr_ratio}")
    print(f"  vol_mult    = {best.params.vol_mult}")
    print(f"  hammer_tail = {best.params.hammer_tail}")
    print(f"  hammer_body = {best.params.hammer_body}")
    best.report.print("최적 파라미터 성과")


def main() -> None:
    parser = argparse.ArgumentParser(description="원캔들 단타 백테스트")
    parser.add_argument("--optimize", action="store_true", help="파라미터 Grid Search")
    args = parser.parse_args()

    if args.optimize:
        run_optimize(args)
    else:
        run_single(args)


if __name__ == "__main__":
    main()
