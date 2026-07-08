"""성과 리포트 — 거래 리스트 → 핵심 지표 계산"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backtest.engine import Trade


@dataclass
class BacktestReport:
    total_trades: int
    wins: int
    losses: int
    win_rate: float          # %
    profit_factor: float     # 총이익 / 총손실
    total_pnl: float         # 원
    avg_win: float
    avg_loss: float
    max_win: float
    max_loss: float
    mdd: float               # Maximum Drawdown %
    sharpe: float            # 연간 샤프 비율 (근사)
    long_count: int
    short_count: int
    tp_count: int
    sl_count: int
    close_count: int

    @classmethod
    def from_trades(
        cls,
        trades: list[Trade],
        initial_equity: float = 10_000_000,
    ) -> "BacktestReport":
        if not trades:
            return cls(
                total_trades=0, wins=0, losses=0, win_rate=0.0,
                profit_factor=0.0, total_pnl=0.0, avg_win=0.0, avg_loss=0.0,
                max_win=0.0, max_loss=0.0, mdd=0.0, sharpe=0.0,
                long_count=0, short_count=0, tp_count=0, sl_count=0, close_count=0,
            )

        pnl_list = [t.pnl_net for t in trades]   # 수수료 반영 실질 손익
        wins_pnl  = [p for p in pnl_list if p > 0]
        loss_pnl  = [p for p in pnl_list if p <= 0]

        total_profit = sum(wins_pnl) if wins_pnl else 0.0
        total_loss   = abs(sum(loss_pnl)) if loss_pnl else 0.0

        return cls(
            total_trades  = len(trades),
            wins          = len(wins_pnl),
            losses        = len(loss_pnl),
            win_rate      = len(wins_pnl) / len(trades) * 100,
            profit_factor = total_profit / total_loss if total_loss > 0 else float("inf"),
            total_pnl     = sum(pnl_list),
            avg_win       = total_profit / len(wins_pnl) if wins_pnl else 0.0,
            avg_loss      = -total_loss / len(loss_pnl) if loss_pnl else 0.0,
            max_win       = max(wins_pnl) if wins_pnl else 0.0,
            max_loss      = min(loss_pnl) if loss_pnl else 0.0,
            mdd           = _calc_mdd(pnl_list, initial_equity),
            sharpe        = _calc_sharpe(pnl_list, initial_equity),  # 수익률 기반으로 변경
            long_count    = sum(1 for t in trades if t.direction == "LONG"),
            short_count   = sum(1 for t in trades if t.direction == "SHORT"),
            tp_count      = sum(1 for t in trades if t.exit_reason == "TP"),
            sl_count      = sum(1 for t in trades if t.exit_reason == "SL"),
            close_count   = sum(1 for t in trades if t.exit_reason == "CLOSE"),
        )

    def print(self, title: str = "") -> None:
        sep = "=" * 46
        print(f"\n{sep}")
        if title:
            print(f"  {title}")
            print(sep)
        print(f"  총 거래 수   : {self.total_trades:>6}")
        print(f"  승/패        : {self.wins}/{self.losses}")
        print(f"  승률         : {self.win_rate:>6.1f}%  (목표 55%)")
        print(f"  손익비(PF)   : {self.profit_factor:>6.2f}  (목표 2.0)")
        print(f"  MDD          : {self.mdd:>6.1f}%  (허용 15%)")
        print(f"  샤프 비율    : {self.sharpe:>6.2f}  (목표 1.5)")
        print(f"  총 손익      : {self.total_pnl:>+12,.0f}원")
        print(f"  평균 수익    : {self.avg_win:>+10,.0f}원")
        print(f"  평균 손실    : {self.avg_loss:>+10,.0f}원")
        print(f"  최대 단일 수익: {self.max_win:>+10,.0f}원")
        print(f"  최대 단일 손실: {self.max_loss:>+10,.0f}원")
        print(f"  Long/Short   : {self.long_count}/{self.short_count}")
        print(f"  TP/SL/CLOSE  : {self.tp_count}/{self.sl_count}/{self.close_count}")
        print(sep)
        self._print_verdict()

    def _print_verdict(self) -> None:
        ok = []
        ng = []
        (ok if self.win_rate >= 55   else ng).append(f"승률 {self.win_rate:.1f}%")
        (ok if self.profit_factor >= 2.0 else ng).append(f"PF {self.profit_factor:.2f}")
        (ok if self.mdd <= 15        else ng).append(f"MDD {self.mdd:.1f}%")
        (ok if self.sharpe >= 1.5    else ng).append(f"샤프 {self.sharpe:.2f}")
        if ng:
            print(f"  ✗ 기준 미달: {', '.join(ng)}")
        if ok:
            print(f"  ✓ 기준 충족: {', '.join(ok)}")


# ------------------------------------------------------------------ #
#  내부 계산                                                           #
# ------------------------------------------------------------------ #

def _calc_mdd(pnl_list: list[float], initial_equity: float) -> float:
    """자산 곡선 기반 MDD (%)"""
    equity = initial_equity
    peak   = equity
    mdd    = 0.0
    for pnl in pnl_list:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > mdd:
            mdd = dd
    return round(mdd, 2)


def _calc_sharpe(pnl_list: list[float], initial_equity: float = 10_000_000, trading_days: int = 252) -> float:
    """
    연간 샤프 비율 (무위험 수익률 = 0 가정)
    수수료 반영된 수익률(%) 기반으로 계산 — 자본 규모와 무관하게 비교 가능.
    단타 기준: 거래 1건 = 1거래일로 환산
    """
    if len(pnl_list) < 2:
        return 0.0
    # 수익률(%) 변환: 원 단위 PnL → 자본 대비 비율
    ret_list = [p / initial_equity for p in pnl_list]
    n    = len(ret_list)
    mean = sum(ret_list) / n
    var  = sum((x - mean) ** 2 for x in ret_list) / (n - 1)
    std  = math.sqrt(var)
    if std == 0:
        return 0.0
    # 단타: 실제 거래 빈도 기준 연환산 (252 거래일 중 실제 n건 비율 적용)
    daily_sharpe  = mean / std
    annual_sharpe = daily_sharpe * math.sqrt(trading_days)
    return round(annual_sharpe, 2)
