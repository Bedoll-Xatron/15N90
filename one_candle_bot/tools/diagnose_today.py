"""오늘 분봉 신호 없음 원인 진단"""
import sys, os
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.basicConfig(level=logging.WARNING)

from backtest.data_loader import load_stock_ohlcv, load_market_proxy
from backtest.engine import BacktestParams, _daily_to_atr_rows, _daily_to_vol_rows
from backtest.minute_loader import load_minute_candles
from market.data_processor import (
    calc_atr, calc_avg_daily_volume, get_first_15m_candle,
    BoxRange, aggregate_candles,
)
from strategy.filters import check_atr_filter, check_volume_filter, check_market_direction
from strategy.pattern import detect_entry_signal
from backtest.engine import _detect_signal_with_params

TODAY   = date.today().strftime("%Y%m%d")
START   = "20230101"
END     = TODAY
PARAMS  = BacktestParams()
TICKERS = {"005930": "삼성전자", "000660": "SK하이닉스", "068270": "셀트리온"}

market = load_market_proxy(START, END)

for ticker, name in TICKERS.items():
    print(f"\n{'='*52}")
    print(f"  {name} ({ticker})  {TODAY}")
    print(f"{'='*52}")

    # 분봉 로드
    candles = load_minute_candles(ticker, TODAY)
    if not candles:
        print("  분봉 데이터 없음")
        continue
    print(f"  분봉 수: {len(candles)}개  ({candles[0].time}~{candles[-1].time})")

    # 일봉 로드
    ohlcv = load_stock_ohlcv(ticker, START, END)
    if ohlcv.empty:
        print("  일봉 데이터 없음"); continue
    daily_idx = {d.strftime("%Y%m%d"): i for i, d in enumerate(ohlcv.index)}
    i = daily_idx.get(TODAY)
    if i is None or i < PARAMS.atr_period + 1:
        print(f"  일봉 인덱스 없음 (i={i})"); continue

    # ATR
    atr_rows = _daily_to_atr_rows(ohlcv.iloc[i - PARAMS.atr_period - 1: i])
    try:
        atr = calc_atr(atr_rows, PARAMS.atr_period)
    except ValueError as e:
        print(f"  ATR 계산 실패: {e}"); continue

    # 첫 15분봉
    first_15m = get_first_15m_candle(candles)
    if first_15m is None:
        print("  09:00~09:14 데이터 없음"); continue
    box = BoxRange(high=first_15m.high, low=first_15m.low)

    print(f"\n  [첫 15분봉] O:{first_15m.open:,} H:{first_15m.high:,} L:{first_15m.low:,} C:{first_15m.close:,}")
    print(f"  박스 크기: {box.size:,.0f}원   ATR(14): {atr:,.0f}원")

    # ATR 필터
    atr_r = check_atr_filter(box.size, atr, PARAMS.atr_ratio)
    print(f"\n  ATR 필터 ({PARAMS.atr_ratio:.0%}): {'✓ 통과' if atr_r.passed else '✗ 탈락'}  {atr_r.reason}")

    # 거래량 필터
    vol_rows = _daily_to_vol_rows(ohlcv.iloc[max(0, i-20): i])
    avg_daily = calc_avg_daily_volume(vol_rows, 20)
    avg_15m   = avg_daily / 26
    vol_r = check_volume_filter(first_15m.volume, avg_15m, PARAMS.vol_mult)
    print(f"  거래량 필터 ({PARAMS.vol_mult}x): {'✓ 통과' if vol_r.passed else '✗ 탈락'}  {vol_r.reason}")

    # 시장 방향
    sig_ts  = ohlcv.index[i]
    mkt_row = market.reindex([sig_ts]).fillna(0.0)
    kospi   = float(mkt_row["kospi_chg"].iloc[0])
    kosdaq  = float(mkt_row["kosdaq_chg"].iloc[0])
    mkt_dir = check_market_direction(kospi, kosdaq, PARAMS.market_pct)
    print(f"  시장 방향: KOSPI {kospi:+.2f}%  KOSDAQ {kosdaq:+.2f}%  → Long허용:{mkt_dir.long_allowed}  Short허용:{mkt_dir.short_allowed}")

    # 5분봉 패턴 스캔
    trading = [c for c in candles if "091500" <= c.time <= "103000"]
    five_min = aggregate_candles(trading, 5)
    print(f"\n  5분봉 수(09:15~10:30): {len(five_min)}개")

    signal_found = False
    for j in range(1, len(five_min)):
        curr = five_min[j]
        prev = five_min[j - 1]
        broke_down = curr.low  < box.low
        broke_up   = curr.high > box.high
        if not (broke_down or broke_up):
            continue
        direction = "하방 이탈" if broke_down else "상방 이탈"
        sig = _detect_signal_with_params(curr, prev, box, PARAMS)
        if sig:
            print(f"\n  ★ 신호 발견! [{curr.time}] {direction} → {sig.direction.value} {sig.pattern.value}")
            print(f"    진입:{sig.trigger_price:,}  손절:{sig.stop_loss:,}  익절:{sig.take_profit:,}")
            signal_found = True
        else:
            print(f"  [{curr.time}] {direction} (O:{curr.open:,} H:{curr.high:,} L:{curr.low:,} C:{curr.close:,}) — 패턴 없음")

    if not signal_found:
        if not atr_r.passed:
            print("\n  → ATR 필터에서 탈락 (박스가 너무 작음)")
        elif not vol_r.passed:
            print("\n  → 거래량 필터에서 탈락 (거래량 부족)")
        elif not any(c.low < box.low or c.high > box.high for c in five_min[1:]):
            print("\n  → 09:15~10:30 박스 이탈 없음 (오늘 조용한 장)")
        else:
            print("\n  → 이탈은 있었지만 망치/장악형 패턴 미충족")
