"""
백테스트 신호 진단 스크립트

각 필터 단계별로 몇 개가 통과하는지 출력해서
신호가 너무 적을 때 원인을 파악합니다.

사용법:
  python run_diagnose.py
"""
import logging
logging.basicConfig(level=logging.WARNING)

from backtest.data_loader import load_stock_ohlcv, load_market_proxy
from backtest.engine import BacktestParams, _row_to_candle, _daily_to_atr_rows, _daily_to_vol_rows
from market.data_processor import BoxRange, calc_atr, calc_avg_daily_volume
from strategy.filters import check_atr_filter, check_volume_filter, check_market_direction
from strategy.pattern import detect_entry_signal

START  = "20230101"
END    = "20241231"

TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "068270": "셀트리온",
}

PARAMS = BacktestParams()


def diagnose(ticker: str, name: str, ohlcv, market) -> None:
    print(f"\n{'─'*50}")
    print(f"  {name} ({ticker})  {len(ohlcv)}일")
    print(f"{'─'*50}")

    n = len(ohlcv)
    dates = ohlcv.index.tolist()

    cnt = {"total": 0, "atr": 0, "vol": 0, "mkt": 0, "pattern": 0}

    for i in range(PARAMS.atr_period + 1, n - 1):
        cnt["total"] += 1
        sig_date = dates[i]

        # ATR 필터
        atr_rows = _daily_to_atr_rows(ohlcv.iloc[i - PARAMS.atr_period - 1: i])
        try:
            atr = calc_atr(atr_rows, PARAMS.atr_period)
        except ValueError:
            continue

        row_prev = ohlcv.iloc[i - 1]
        box = BoxRange(high=float(row_prev["high"]), low=float(row_prev["low"]))
        atr_ok = check_atr_filter(box.size, atr, PARAMS.atr_ratio).passed
        if atr_ok:
            cnt["atr"] += 1

        # 거래량 필터
        vol_rows = _daily_to_vol_rows(ohlcv.iloc[max(0, i - 20): i])
        avg_vol = calc_avg_daily_volume(vol_rows, 20)
        vol_ok = check_volume_filter(int(ohlcv.iloc[i]["volume"]), avg_vol, PARAMS.vol_mult).passed
        if atr_ok and vol_ok:
            cnt["vol"] += 1

        # 시장 방향 필터
        mkt = market.reindex([sig_date]).fillna(0.0)
        kospi  = float(mkt["kospi_chg"].iloc[0])  if not mkt.empty else 0.0
        kosdaq = float(mkt["kosdaq_chg"].iloc[0]) if not mkt.empty else 0.0
        mkt_dir = check_market_direction(kospi, kosdaq, PARAMS.market_pct)
        if atr_ok and vol_ok and mkt_dir.any_allowed:
            cnt["mkt"] += 1

        # 패턴
        if atr_ok and vol_ok and mkt_dir.any_allowed:
            curr = _row_to_candle(ohlcv.iloc[i])
            prev = _row_to_candle(ohlcv.iloc[i - 1])
            from backtest.engine import _detect_signal_with_params
            sig = _detect_signal_with_params(curr, prev, box, PARAMS)
            if sig and mkt_dir.allows(sig.direction):
                cnt["pattern"] += 1

    print(f"  전체 거래일       : {cnt['total']:>4}일")
    print(f"  ATR 필터 통과     : {cnt['atr']:>4}일  ({cnt['atr']/cnt['total']*100:.1f}%)")
    print(f"  + 거래량 필터     : {cnt['vol']:>4}일  ({cnt['vol']/cnt['total']*100:.1f}%)")
    print(f"  + 시장 방향 필터  : {cnt['mkt']:>4}일  ({cnt['mkt']/cnt['total']*100:.1f}%)")
    print(f"  + 패턴 신호       : {cnt['pattern']:>4}건  ← 최종 신호 수")
    print()
    if cnt["atr"] == 0:
        print("  ⚠ ATR 필터가 너무 타이트합니다.")
        print(f"    현재 atr_ratio={PARAMS.atr_ratio}  →  0.20 이하로 낮춰보세요.")
    if cnt["vol"] == 0 and cnt["atr"] > 0:
        print("  ⚠ 거래량 필터가 너무 타이트합니다.")
        print(f"    현재 vol_mult={PARAMS.vol_mult}  →  1.2 이하로 낮춰보세요.")


def main() -> None:
    print("=" * 50)
    print("  원캔들 전략 — 필터 단계별 진단")
    print(f"  기간: {START} ~ {END}")
    print(f"  파라미터: ATR={PARAMS.atr_ratio}  Vol={PARAMS.vol_mult}  "
          f"Tail={PARAMS.hammer_tail}  Body={PARAMS.hammer_body}")
    print("=" * 50)

    market = load_market_proxy(START, END)
    for ticker, name in TICKERS.items():
        ohlcv = load_stock_ohlcv(ticker, START, END)
        if ohlcv.empty:
            print(f"  {name}: 데이터 없음")
            continue
        diagnose(ticker, name, ohlcv, market)


if __name__ == "__main__":
    main()
