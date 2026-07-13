"""
0단계: 일봉 근사 백테스트 엔진

⚠ 일봉 근사 주의사항
  - 실제 전략은 15분봉/5분봉 기반 (09:00~10:30)
  - 여기서는 전일 캔들 = 박스, 당일 캔들 = 이탈+반전 신호로 근사
  - 목적: 전략 방향성과 파라미터 범위 사전 검증 (정확한 성과 수치 아님)

근사 매핑
  전일 고가/저가  → 15분봉 박스 상단/하단
  당일 일봉 패턴  → 5분봉 반전 패턴
  당일 close     → 진입가
  익일 고가/저가  → 익절/손절 체크
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from market.data_processor import BoxRange, Candle, calc_atr
from strategy.filters import (
    check_atr_filter, check_volume_filter, check_market_direction, Direction,
)
from strategy.pattern import detect_entry_signal, EntryType
from strategy.position_sizer import calc_position_size

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  파라미터                                                            #
# ------------------------------------------------------------------ #

@dataclass
class BacktestParams:
    atr_period: int   = 14
    atr_ratio: float  = 0.20
    box_vol_ratio: float = 0.20
    hammer_tail: float = 0.50
    hammer_body: float = 0.35
    market_pct: float  = 1.5
    risk_pct: float    = 0.01
    max_invest_pct: float = 0.20


# ------------------------------------------------------------------ #
#  거래 기록                                                           #
# ------------------------------------------------------------------ #

# 왕복 실질 비용: 매수 수수료 0.015% + 매도 수수료 0.015% + 증권거래세 0.2% + 슬리피지 0.05%×2
COMMISSION_BUY  = 0.00015 + 0.0005   # 0.065%
COMMISSION_SELL = 0.00015 + 0.002 + 0.0005  # 0.265%
COMMISSION_ROUND_TRIP = COMMISSION_BUY + COMMISSION_SELL  # ≈ 0.33%


@dataclass
class Trade:
    date: str           # 신호 발생일 (YYYY-MM-DD)
    ticker: str
    direction: str      # LONG / SHORT
    pattern: str
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    exit_reason: str    # TP / SL / CLOSE
    shares: int = 1     # 보유 주식 수 (pnl_net 계산용)

    @property
    def pnl(self) -> float:
        """수수료 미반영 주당 손익 (원)"""
        if self.direction == "LONG":
            return self.exit_price - self.entry_price
        return self.entry_price - self.exit_price

    @property
    def commission(self) -> float:
        """왕복 수수료 (원) — 매수 0.065% + 매도 0.265%"""
        buy_cost  = self.entry_price * self.shares * COMMISSION_BUY
        sell_cost = self.exit_price  * self.shares * COMMISSION_SELL
        return buy_cost + sell_cost

    @property
    def pnl_net(self) -> float:
        """수수료 반영 실질 손익 (원)"""
        gross = self.pnl * self.shares
        return gross - self.commission

    @property
    def is_win(self) -> bool:
        return self.pnl_net > 0


# ------------------------------------------------------------------ #
#  일봉 → Candle 변환 헬퍼                                            #
# ------------------------------------------------------------------ #

def _row_to_candle(row: pd.Series, time: str = "000000") -> Candle:
    return Candle(
        time=time,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
    )


def _daily_to_atr_rows(df_slice: pd.DataFrame) -> list[dict]:
    """ATR 계산용 포맷으로 변환 (최신순)"""
    rows = []
    for _, r in df_slice.iloc[::-1].iterrows():
        rows.append({
            "stck_hgpr": str(r["high"]),
            "stck_lwpr": str(r["low"]),
            "stck_clpr": str(r["close"]),
        })
    return rows


def _daily_to_vol_rows(df_slice: pd.DataFrame) -> list[dict]:
    """거래량 평균용 포맷으로 변환"""
    return [{"acml_vol": str(int(r["volume"]))} for _, r in df_slice.iterrows()]


# ------------------------------------------------------------------ #
#  메인 시뮬레이션                                                     #
# ------------------------------------------------------------------ #

def simulate_one_stock(
    ohlcv: pd.DataFrame,
    market: pd.DataFrame,
    ticker: str,
    params: BacktestParams,
    initial_equity: float = 10_000_000,
) -> list[Trade]:
    """
    단일 종목 일봉 백테스트 실행.

    Parameters
    ----------
    ohlcv   : load_stock_ohlcv() 반환 DataFrame (날짜 오름차순)
    market  : load_market_proxy() 반환 DataFrame
    ticker  : 종목 코드 (로그용)
    params  : BacktestParams
    """
    if len(ohlcv) < params.atr_period + 3:
        logger.warning(f"[{ticker}] 데이터 부족 ({len(ohlcv)}일)")
        return []

    trades: list[Trade] = []
    equity = initial_equity
    dates  = ohlcv.index.tolist()

    # ATR 계산 최소 기간(atr_period+1) + 1일(전일 박스) + 1일(익일 청산)
    start_i = params.atr_period + 1

    for i in range(start_i, len(dates) - 1):
        sig_date  = dates[i]
        exit_date = dates[i + 1]

        row_today = ohlcv.iloc[i]
        row_prev  = ohlcv.iloc[i - 1]
        row_exit  = ohlcv.iloc[i + 1]

        # ── 시장 방향 필터 ──
        mkt = market.reindex([sig_date]).fillna(0.0)
        kospi_chg  = float(mkt["kospi_chg"].iloc[0])  if not mkt.empty else 0.0
        kosdaq_chg = float(mkt["kosdaq_chg"].iloc[0]) if not mkt.empty else 0.0
        mkt_dir = check_market_direction(kospi_chg, kosdaq_chg, params.market_pct)

        if not mkt_dir.any_allowed:
            continue

        # ── ATR 계산 ──
        atr_rows = _daily_to_atr_rows(ohlcv.iloc[i - params.atr_period - 1: i])
        try:
            atr = calc_atr(atr_rows, params.atr_period)
        except ValueError:
            continue

        # ── 전일 박스 확정 ──
        box = BoxRange(high=float(row_prev["high"]), low=float(row_prev["low"]))

        atr_result = check_atr_filter(box.size, atr, params.atr_ratio)
        if not atr_result.passed:
            continue

        # ── 거래량 폭발 필터 (근사 백테스트이므로 당일 전체 거래량이 최소 box_vol_ratio 이상이어야 함을 검증) ──
        vol_rows = _daily_to_vol_rows(ohlcv.iloc[max(0, i - 20): i])
        from market.data_processor import calc_avg_daily_volume
        avg_vol = calc_avg_daily_volume(vol_rows, 20)
        
        # 실제 분봉에서는 15분만에 20%가 터지는지 확인하지만, 
        # 일봉 근사 백테스트에서는 당일 거래량 전체가 15분 폭발 목표치(20%)보다 크기만 하면 1차 패스
        if avg_vol > 0 and int(row_today["volume"]) < avg_vol * params.box_vol_ratio:
            continue

        # ── 패턴 감지 ──
        curr = _row_to_candle(row_today)
        prev = _row_to_candle(row_prev)

        # config override: 파라미터 Grid 적용
        from config import STRATEGY
        import strategy.pattern as _pat
        signal = _pat.detect_entry_signal.__wrapped__(curr, prev, box) \
            if hasattr(_pat.detect_entry_signal, "__wrapped__") \
            else _detect_signal_with_params(curr, prev, box, params)

        if signal is None:
            continue

        # 시장 방향 허용 체크
        if not mkt_dir.allows(signal.direction):
            continue

        # ── 포지션 사이즈 ──
        try:
            pos = calc_position_size(
                equity=equity,
                entry_price=signal.trigger_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_pct=params.risk_pct,
                max_invest_pct=params.max_invest_pct,
            )
        except ValueError:
            continue

        # ── 익일 청산 시뮬레이션 ──
        exit_price, exit_reason = _simulate_exit(
            direction=signal.direction,
            entry=signal.trigger_price,
            stop=signal.stop_loss,
            tp=signal.take_profit,
            next_row=row_exit,
        )

        trade = Trade(
            date=str(sig_date.date()) if hasattr(sig_date, "date") else str(sig_date),
            ticker=ticker,
            direction=signal.direction.value,
            pattern=signal.pattern.value,
            entry_price=signal.trigger_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            exit_price=exit_price,
            exit_reason=exit_reason,
        )
        trades.append(trade)

        # 자산 업데이트 (단순 손익 반영)
        equity += trade.pnl * pos.shares

        logger.debug(
            f"[{ticker}] {trade.date} {trade.direction} "
            f"진입:{trade.entry_price:,.0f} 청산:{trade.exit_price:,.0f} "
            f"→ {'WIN' if trade.is_win else 'LOSS'} ({trade.exit_reason})"
        )

    return trades


def _detect_signal_with_params(
    curr: Candle,
    prev: Candle,
    box: BoxRange,
    params: BacktestParams,
):
    """파라미터 오버라이드 버전 패턴 탐지"""
    from strategy.pattern import (
        is_hammer, is_shooting_star,
        is_bullish_engulfing, is_bearish_engulfing,
        EntrySignal, PatternType, EntryType,
        _long_stop, _short_stop,
    )

    broke_down = curr.low  < box.low
    broke_up   = curr.high > box.high

    if broke_down and broke_up:
        return None

    if broke_down:
        if is_hammer(curr, params.hammer_tail, params.hammer_body):
            return EntrySignal(
                direction=Direction.LONG, pattern=PatternType.HAMMER,
                entry_type=EntryType.TRIGGER, trigger_price=curr.high,
                stop_loss=_long_stop(curr.low), take_profit=box.high, candle_time=curr.time,
            )
        if is_bullish_engulfing(curr, prev) and prev.low < box.low:
            return EntrySignal(
                direction=Direction.LONG, pattern=PatternType.BULLISH_ENGULF,
                entry_type=EntryType.IMMEDIATE, trigger_price=curr.close,
                stop_loss=_long_stop(min(curr.low, prev.low)), take_profit=box.high, candle_time=curr.time,
            )

    if broke_up:
        if is_shooting_star(curr, params.hammer_tail, params.hammer_body):
            return EntrySignal(
                direction=Direction.SHORT, pattern=PatternType.SHOOTING_STAR,
                entry_type=EntryType.TRIGGER, trigger_price=curr.low,
                stop_loss=_short_stop(curr.high), take_profit=box.low, candle_time=curr.time,
            )
        if is_bearish_engulfing(curr, prev) and prev.high > box.high:
            return EntrySignal(
                direction=Direction.SHORT, pattern=PatternType.BEARISH_ENGULF,
                entry_type=EntryType.IMMEDIATE, trigger_price=curr.close,
                stop_loss=_short_stop(max(curr.high, prev.high)), take_profit=box.low, candle_time=curr.time,
            )

    return None


def _simulate_exit(
    direction: Direction,
    entry: float,
    stop: float,
    tp: float,
    next_row: pd.Series,
) -> tuple[float, str]:
    """
    익일 고/저가로 청산 시뮬레이션.
    둘 다 걸리면 손절 우선 (보수적 처리).
    """
    h = float(next_row["high"])
    l = float(next_row["low"])
    c = float(next_row["close"])

    if direction == Direction.LONG:
        sl_hit = l <= stop
        tp_hit = h >= tp
        if sl_hit and tp_hit:
            return stop, "SL"   # 보수적: 손절 우선
        if sl_hit:
            return stop, "SL"
        if tp_hit:
            return tp,   "TP"
        return c, "CLOSE"

    else:  # SHORT
        sl_hit = h >= stop
        tp_hit = l <= tp
        if sl_hit and tp_hit:
            return stop, "SL"
        if sl_hit:
            return stop, "SL"
        if tp_hit:
            return tp,   "TP"
        return c, "CLOSE"
