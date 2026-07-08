"""
일일 손실 한도 관리 모듈

당일 누적 실현 손익이 설정한 한도 이하로 떨어지면
당일 신규 진입을 자동으로 차단합니다.

기본 설정: 초기 자본 대비 -2% 도달 시 거래 중단
"""
import logging

logger = logging.getLogger(__name__)


class DailyLimitManager:
    """
    당일 손실 한도 감시자.

    Parameters
    ----------
    initial_balance : 전략 계좌의 초기 잔고 (당일 기준)
    max_loss_pct    : 허용 최대 손실 비율 (기본 2%)
    strategy_id     : 텔레그램 알림용 전략 식별자 (A/B/C)
    """

    def __init__(
        self,
        initial_balance: float,
        max_loss_pct: float = 0.02,
        strategy_id: str = "?",
    ):
        self.initial_balance  = initial_balance
        self.max_loss_pct     = max_loss_pct
        self.strategy_id      = strategy_id
        self.daily_loss_limit = initial_balance * max_loss_pct  # 허용 손실 금액
        self.realized_pnl     = 0.0                             # 당일 누적 실현 손익
        self._halted          = False

    # ------------------------------------------------------------------ #
    #  상태 업데이트                                                       #
    # ------------------------------------------------------------------ #

    def record_pnl(self, pnl: float) -> None:
        """청산 시마다 실현 손익을 누적합니다."""
        self.realized_pnl += pnl
        logger.debug(
            f"[전략 {self.strategy_id}] 당일 누적 손익: {self.realized_pnl:+,.0f}원 "
            f"(한도: -{self.daily_loss_limit:,.0f}원)"
        )

    # ------------------------------------------------------------------ #
    #  한도 체크                                                           #
    # ------------------------------------------------------------------ #

    @property
    def halted(self) -> bool:
        """당일 거래가 중단된 상태인지 반환합니다."""
        if self._halted:
            return True
        if self.realized_pnl <= -self.daily_loss_limit:
            self._halted = True
            loss_pct = abs(self.realized_pnl) / self.initial_balance * 100
            logger.warning(
                f"[전략 {self.strategy_id}] ⛔ 일일 손실 한도 도달! "
                f"누적 손실: {self.realized_pnl:,.0f}원 ({loss_pct:.1f}%) "
                f"→ 당일 신규 진입 차단"
            )
        return self._halted

    def can_enter(self) -> bool:
        """신규 진입이 가능한지 여부를 반환합니다."""
        return not self.halted

    # ------------------------------------------------------------------ #
    #  요약                                                                #
    # ------------------------------------------------------------------ #

    def summary(self) -> str:
        loss_pct = abs(min(self.realized_pnl, 0)) / self.initial_balance * 100
        return (
            f"[전략 {self.strategy_id}] 일일 손익: {self.realized_pnl:+,.0f}원 "
            f"(손실률: {loss_pct:.1f}% / 한도: {self.max_loss_pct*100:.0f}%) "
            f"→ {'⛔ 거래 중단' if self.halted else '✅ 거래 가능'}"
        )
