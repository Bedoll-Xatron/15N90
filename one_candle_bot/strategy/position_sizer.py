"""
4단계: ATR 기반 포지션 사이즈 계산 모듈

원칙: 거래당 손실이 계좌의 일정 비율을 넘지 않도록 주식 수 결정.
  매수 수량 = (계좌 × 리스크%) / 손절폭(원)

백테스트와 수동 계산 모두 사용 가능. 매매 실행 코드 없음.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from config import StrategyConfig, STRATEGY


@dataclass(frozen=True)
class PositionSize:
    shares: int              # 매수(매도) 주식 수
    entry_price: float       # 진입 가격
    stop_loss: float         # 손절 가격
    take_profit: float       # 익절 가격
    risk_amount: float       # 실제 리스크 금액 (원)
    invest_amount: float     # 총 투자 금액 (원)
    risk_pct: float          # 계좌 대비 리스크 비율

    @property
    def stop_gap(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def profit_gap(self) -> float:
        return abs(self.take_profit - self.entry_price)

    @property
    def rr_ratio(self) -> float:
        return round(self.profit_gap / self.stop_gap, 2) if self.stop_gap > 0 else 0.0

    @property
    def expected_profit(self) -> float:
        return self.shares * self.profit_gap

    @property
    def expected_loss(self) -> float:
        return self.shares * self.stop_gap

    def summary(self) -> str:
        return (
            f"수량    : {self.shares:>6,}주\n"
            f"진입가  : {self.entry_price:>10,.0f}원\n"
            f"손절선  : {self.stop_loss:>10,.0f}원  (gap {self.stop_gap:,.0f})\n"
            f"익절선  : {self.take_profit:>10,.0f}원  (gap {self.profit_gap:,.0f})\n"
            f"손익비  : {self.rr_ratio:.1f}\n"
            f"투자금  : {self.invest_amount:>10,.0f}원\n"
            f"최대손실: {self.expected_loss:>10,.0f}원  ({self.risk_pct:.2%})\n"
            f"기대수익: {self.expected_profit:>10,.0f}원"
        )


class PositionSizer:
    """
    ATR 기반 포지션 사이즈 계산기.

    Parameters
    ----------
    equity       : 현재 계좌 평가금액 (원)
    risk_pct     : 거래당 최대 손실 허용 비율 (기본 1%)
    max_invest_pct : 단일 종목 최대 투자 비율 (기본 20%)
    """

    def __init__(
        self,
        equity: float,
        risk_pct: float = 0.01,
        max_invest_pct: float = 0.20,
    ) -> None:
        if equity <= 0:
            raise ValueError("equity는 0보다 커야 합니다.")
        if not (0 < risk_pct <= 0.05):
            raise ValueError("risk_pct는 0~5% 사이여야 합니다.")
        if not (0 < max_invest_pct <= 1.0):
            raise ValueError("max_invest_pct는 0~100% 사이여야 합니다.")

        self.equity = equity
        self.risk_pct = risk_pct
        self.max_invest_pct = max_invest_pct

    def calc(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> PositionSize:
        """
        진입가 / 손절가 / 익절가로 적정 주식 수 계산.

        Raises
        ------
        ValueError : 가격 조건이 잘못된 경우 (손절이 진입 반대편에 없을 때 등)
        """
        self._validate_prices(entry_price, stop_loss, take_profit)

        stop_gap = abs(entry_price - stop_loss)
        risk_amount = self.equity * self.risk_pct          # 허용 손실 금액
        max_invest  = self.equity * self.max_invest_pct    # 최대 투자 금액

        # 기본 수량: 리스크 금액 / 손절폭
        raw_shares = risk_amount / stop_gap
        # 투자금 상한으로 추가 제한
        cap_shares = max_invest / entry_price

        shares = max(1, math.floor(min(raw_shares, cap_shares)))

        actual_invest = shares * entry_price
        actual_risk   = shares * stop_gap
        actual_risk_pct = actual_risk / self.equity

        return PositionSize(
            shares=shares,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=actual_risk,
            invest_amount=actual_invest,
            risk_pct=actual_risk_pct,
        )

    # ------------------------------------------------------------------ #
    #  내부                                                                #
    # ------------------------------------------------------------------ #

    def _validate_prices(
        self,
        entry: float,
        stop: float,
        tp: float,
    ) -> None:
        if entry <= 0 or stop <= 0 or tp <= 0:
            raise ValueError("가격은 모두 0보다 커야 합니다.")
        if entry == stop:
            raise ValueError("진입가와 손절가가 같습니다.")

        is_long = stop < entry
        if is_long and tp <= entry:
            raise ValueError("Long: 익절가는 진입가보다 높아야 합니다.")
        if not is_long and tp >= entry:
            raise ValueError("Short: 익절가는 진입가보다 낮아야 합니다.")


# ------------------------------------------------------------------ #
#  편의 함수                                                            #
# ------------------------------------------------------------------ #

def calc_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    risk_pct: float = 0.01,
    max_invest_pct: float = 0.20,
) -> PositionSize:
    """PositionSizer 를 직접 쓰지 않을 때의 단축 함수."""
    return PositionSizer(equity, risk_pct, max_invest_pct).calc(
        entry_price, stop_loss, take_profit
    )
