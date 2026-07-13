"""
0단계: 분봉 기반 백테스트 엔진 (정확한 버전)

실제 15분봉 박스 + 5분봉 패턴으로 engine.py 의 일봉 근사를 대체.

흐름 (하루 기준):
  1. 일봉 데이터로 ATR 계산
  2. 분봉 CSV 로드 → 1분봉 파싱
  3. 첫 15분봉(09:00~09:14) → 박스 확정
  4. 필터 통과 여부 확인 (ATR, 거래량, 시장방향)
  5. 5분봉 09:15~10:30 순회 → 패턴 탐지
  6. 신호 발생 시 이후 1분봉으로 익절/손절 시뮬레이션
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from backtest.engine import BacktestParams, Trade, _daily_to_atr_rows, _daily_to_vol_rows
from backtest.minute_loader import load_minute_candles
from market.data_processor import (
    BoxRange, Candle,
    aggregate_candles, get_first_15m_candle, calc_atr, calc_avg_daily_volume,
)
from strategy.filters import (
    check_atr_filter, check_volume_filter, check_market_direction,
)
from strategy.pattern import detect_entry_signal, detect_strategy_B, detect_strategy_C
from strategy.position_sizer import calc_position_size

logger = logging.getLogger(__name__)

ENTRY_END   = "103000"   # 신규 진입 마감 시각
FORCE_CLOSE = "145900"   # 강제 청산 시각


# ------------------------------------------------------------------ #
#  분봉 청산 시뮬레이션                                                #
# ------------------------------------------------------------------ #

def _simulate_minute_exit(
    direction: str,
    entry: float,
    stop: float,
    tp: float,
    candles_after: list[Candle],
) -> tuple[float, str]:
    """
    신호 이후 1분봉으로 익절/손절 시뮬레이션.
    - 손익비 2.0(RR 2) 도달 시 50% 익절 후 손절가를 본전으로 상향 (트레일링 스탑)
    - 손절 우선 (same bar 동시 도달 시 보수적 평가)
    - FORCE_CLOSE 시각 도달 시 현재가로 청산
    """
    partial_sold = False
    
    if direction == "LONG":
        rr2_price = entry + (entry - stop) * 2.0
    else:
        rr2_price = entry - (stop - entry) * 2.0

    for c in candles_after:
        if c.time >= FORCE_CLOSE:
            if not partial_sold:
                return c.close, "CLOSE"
            else:
                return (rr2_price + c.close) / 2.0, "PARTIAL_CLOSE"

        if direction == "LONG":
            if c.low <= stop:
                if not partial_sold:
                    return stop, "SL"
                else:
                    return (rr2_price + stop) / 2.0, "PARTIAL_SL"
                    
            if not partial_sold and c.high >= rr2_price:
                partial_sold = True
                stop = entry  # 손절선 본전 상향
                
            if c.high >= tp:
                if not partial_sold:
                    return tp, "TP" # 갭상승 등으로 한 번에 도달 시
                else:
                    return (rr2_price + tp) / 2.0, "PARTIAL_TP"
        else:
            if c.high >= stop:
                if not partial_sold:
                    return stop, "SL"
                else:
                    return (rr2_price + stop) / 2.0, "PARTIAL_SL"
                    
            if not partial_sold and c.low <= rr2_price:
                partial_sold = True
                stop = entry  # 손절선 본전 하향
                
            if c.low <= tp:
                if not partial_sold:
                    return tp, "TP"
                else:
                    return (rr2_price + tp) / 2.0, "PARTIAL_TP"

    # 장 마감까지 미체결
    if candles_after:
        if not partial_sold:
            return candles_after[-1].close, "CLOSE"
        else:
            return (rr2_price + candles_after[-1].close) / 2.0, "PARTIAL_CLOSE"
            
    return entry, "CLOSE"


# ------------------------------------------------------------------ #
#  메인 시뮬레이션                                                     #
# ------------------------------------------------------------------ #

def simulate_minute_stock(
    ticker: str,
    daily_ohlcv: pd.DataFrame,
    market: pd.DataFrame,
    params: BacktestParams,
    initial_equity: float = 10_000_000,
) -> dict[str, list[Trade]]:
    """
    분봉 CSV 파일이 존재하는 날짜에 대해서만 전략 A / B / C 3가지를 독립 백테스트 실행.
    반환값: {전략ID: [Trade 리스트]}

    Parameters
    ----------
    ticker      : 종목코드
    daily_ohlcv : 일봉 OHLCV (ATR / 평균거래량 계산용)
    market      : 시장 방향 DataFrame (load_market_proxy 반환)
    """
    from backtest.minute_loader import available_dates

    dates_with_csv = available_dates(ticker)
    if not dates_with_csv:
        logger.warning(f"[{ticker}] 분봉 CSV 없음  →  backtest/data/{ticker}/ 에 파일을 준비하세요.")
        return {"A": [], "B": [], "C": []}

    trades: dict[str, list[Trade]] = {"A": [], "B": [], "C": []}
    equity = {"A": initial_equity, "B": initial_equity, "C": initial_equity}
    daily_idx = {d.strftime("%Y%m%d"): i for i, d in enumerate(daily_ohlcv.index)}

    # 전략별 신호 감지 함수 맵
    # 일봉 21 EMA 계산 (종목)
    daily_ohlcv["ema21"] = daily_ohlcv["close"].ewm(span=21, adjust=False).mean()

    STRATEGY_DETECTORS = {
        "A": lambda curr, prev, five_min, box: detect_entry_signal(curr, prev, box),
        "B": lambda curr, জ্ঞprev, five_min, box: detect_strategy_B(curr, prev, box),
        "C": lambda curr, prev, five_min, box: detect_strategy_C(five_min, box),
    }

    for yyyymmdd in dates_with_csv:
        i = daily_idx.get(yyyymmdd)
        if i is None or i < params.atr_period + 1:
            continue

        # ── ATR 계산 ──
        atr_rows = _daily_to_atr_rows(daily_ohlcv.iloc[i - params.atr_period - 1: i])
        try:
            atr = calc_atr(atr_rows, params.atr_period)
        except ValueError:
            continue

        # ── 분봉 로드 ──
        minute_candles = load_minute_candles(ticker, yyyymmdd)
        if not minute_candles:
            continue

        # ── 첫 15분봉 박스 ──
        first_15m = get_first_15m_candle(minute_candles)
        if first_15m is None:
            logger.debug(f"[{ticker}] {yyyymmdd} 09:00~09:14 데이터 없음")
            continue

        box = BoxRange(high=first_15m.high, low=first_15m.low)

        # ── ATR 필터 ──
        if not check_atr_filter(box.size, atr, params.atr_ratio).passed:
            continue

        # ── 거래량 폭발 필터 (15분봉 거래량이 일평균의 box_vol_ratio 이상) ──
        vol_rows  = _daily_to_vol_rows(daily_ohlcv.iloc[max(0, i - 20): i])
        avg_daily = calc_avg_daily_volume(vol_rows, 20)
        
        if avg_daily > 0 and first_15m.volume < avg_daily * params.box_vol_ratio:
            continue

        # ── 종목 21 EMA 필터 ──
        if i >= 2:
            ema21_current = float(daily_ohlcv["ema21"].iloc[i-1]) # 어제 종가 기준
            ema21_prev = float(daily_ohlcv["ema21"].iloc[i-2])
            current_close = float(daily_ohlcv["close"].iloc[i-1])
            # V자 우측 (EMA 상승) 및 가격이 EMA 위인지 확인
            if ema21_current <= ema21_prev or current_close < ema21_current:
                continue

        # ── 시장 방향 필터 ──
        sig_ts = daily_ohlcv.index[i]
        mkt = market.reindex([sig_ts]).fillna(0.0)
        kospi  = float(mkt["kospi_chg"].iloc[0])  if not mkt.empty else 0.0
        kosdaq = float(mkt["kosdaq_chg"].iloc[0]) if not mkt.empty else 0.0
        mkt_dir = check_market_direction(kospi, kosdaq, params.market_pct)
        if not mkt_dir.any_allowed:
            continue

        # ── 지수 리스크 필터 (코스피 21 EMA) ──
        risk_multiplier = 1.0
        if not mkt.empty and i >= 2:
            try:
                # mkt 데이터프레임의 이전 날짜 인덱스를 찾아서 EMA 추세 계산 (mkt는 이미 market에서 로드됨)
                # market_df 전체에서 해당 날짜 이전 데이터를 가져와야 함.
                idx_in_market = market.index.get_loc(sig_ts)
                if isinstance(idx_in_market, int) and idx_in_market >= 2:
                    k_ema21_curr = float(market["kospi_ema21"].iloc[idx_in_market-1])
                    k_ema21_prev = float(market["kospi_ema21"].iloc[idx_in_market-2])
                    k_close = float(market["kospi_close"].iloc[idx_in_market-1])
                    if k_ema21_curr <= k_ema21_prev or k_close < k_ema21_curr:
                        risk_multiplier = 0.5
            except Exception as e:
                pass

        # ── 5분봉 집계 (09:15 ~ 10:30) ──
        trading_candles = [c for c in minute_candles if "091500" <= c.time <= ENTRY_END]
        five_min = aggregate_candles(trading_candles, interval_min=5)

        # ── 전략별 독립 패턴 순회 ──
        for s_id, detector in STRATEGY_DETECTORS.items():
            signal_found = False

            for j in range(1, len(five_min)):
                if signal_found:
                    break
                if five_min[j].time > ENTRY_END:
                    break

                curr = five_min[j]
                prev = five_min[j - 1]

                sig = detector(curr, prev, five_min[:j+1], box)
                if sig is None:
                    continue
                if not mkt_dir.allows(sig.direction):
                    continue

                # ── 포지션 사이즈 ──
                try:
                    pos = calc_position_size(
                        equity=equity[s_id] * risk_multiplier,
                        entry_price=sig.trigger_price,
                        stop_loss=sig.stop_loss,
                        take_profit=sig.take_profit,
                        risk_pct=params.risk_pct,
                        max_invest_pct=params.max_invest_pct,
                    )
                except ValueError:
                    continue

                # ── 1분봉으로 청산 시뮬레이션 ──
                after = [c for c in minute_candles if c.time > curr.time]
                exit_price, exit_reason = _simulate_minute_exit(
                    direction=sig.direction.value,
                    entry=sig.trigger_price,
                    stop=sig.stop_loss,
                    tp=sig.take_profit,
                    candles_after=after,
                )

                trade = Trade(
                    date=yyyymmdd,
                    ticker=ticker,
                    direction=sig.direction.value,
                    pattern=sig.pattern.value,
                    entry_price=sig.trigger_price,
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    shares=pos.shares,
                )
                trades[s_id].append(trade)
                equity[s_id] += trade.pnl_net  # 수수료 반영 실질 손익으로 자산 업데이트
                signal_found = True

                logger.info(
                    f"[{ticker}][전략{s_id}] {yyyymmdd} {curr.time} {trade.direction} "
                    f"{trade.pattern} | "
                    f"진입:{trade.entry_price:,.0f} → 청산:{trade.exit_price:,.0f} "
                    f"({trade.exit_reason}) 순수익:{trade.pnl_net:+,.0f}원"
                )

    return trades
