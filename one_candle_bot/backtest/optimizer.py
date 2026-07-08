"""파라미터 Grid Search 최적화 — 분봉 백테스트 기반 (정확도 향상)"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

import pandas as pd

from backtest.engine import BacktestParams, Trade
from backtest.engine_minute import simulate_minute_stock   # 수정: 일봉 근사 → 분봉 정확 엔진
from backtest.report import BacktestReport

logger = logging.getLogger(__name__)


@dataclass
class OptimResult:
    params: BacktestParams
    report: BacktestReport
    score: float       # 최적화 기준값 (profit_factor)
    strategy_id: str = "A"   # 평가 대상 전략

    def summary_row(self) -> dict:
        p = self.params
        r = self.report
        return {
            "strategy":    self.strategy_id,
            "atr_ratio":   p.atr_ratio,
            "vol_mult":    p.vol_mult,
            "hammer_tail": p.hammer_tail,
            "hammer_body": p.hammer_body,
            "trades":      r.total_trades,
            "win_rate":    round(r.win_rate, 1),
            "pf":          round(r.profit_factor, 2),
            "mdd":         round(r.mdd, 1),
            "sharpe":      round(r.sharpe, 2),
        }


# 기본 탐색 범위 (0단계 권장값)
DEFAULT_GRID = {
    "atr_ratio":   [0.25, 0.33, 0.40],
    "vol_mult":    [1.3,  1.5,  2.0],
    "hammer_tail": [0.50, 0.60, 0.70],
    "hammer_body": [0.20, 0.25, 0.30],
}


def optimize(
    stock_data: dict[str, pd.DataFrame],   # {ticker: ohlcv_df}
    market_df: pd.DataFrame,
    param_grid: dict | None = None,
    initial_equity: float = 10_000_000,
    min_trades: int = 5,
    strategies: list[str] = ("A", "B", "C"),
) -> dict[str, list[OptimResult]]:
    """
    분봉 기반 Grid Search 실행 (전략 A/B/C 각각 독립 평가).

    Parameters
    ----------
    stock_data   : {ticker: ohlcv DataFrame} — load_stock_ohlcv() 결과
    market_df    : load_market_proxy() 결과
    param_grid   : 탐색할 파라미터 범위 (None 이면 DEFAULT_GRID 사용)
    min_trades   : 최소 거래 횟수 미달 결과 제외
    strategies   : 평가할 전략 목록

    Returns
    -------
    {전략ID: OptimResult 리스트, profit_factor 내림차순 정렬}
    """
    grid = param_grid or DEFAULT_GRID
    keys   = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total  = len(combos)
    logger.info(f"Grid Search 시작: {total}개 조합 × {len(stock_data)}개 종목 × {len(strategies)}개 전략")

    results: dict[str, list[OptimResult]] = {s: [] for s in strategies}

    for idx, combo in enumerate(combos, 1):
        params = BacktestParams(**dict(zip(keys, combo)))

        # 전략별 모든 거래 합산
        all_trades_by_strategy: dict[str, list[Trade]] = {s: [] for s in strategies}
        for ticker, ohlcv in stock_data.items():
            trade_map = simulate_minute_stock(ohlcv=ohlcv, daily_ohlcv=ohlcv,
                                             market=market_df, ticker=ticker,
                                             params=params, initial_equity=initial_equity)
            for s in strategies:
                all_trades_by_strategy[s].extend(trade_map.get(s, []))

        for s in strategies:
            s_trades = all_trades_by_strategy[s]
            if len(s_trades) < min_trades:
                continue

            report = BacktestReport.from_trades(s_trades, initial_equity)
            score  = report.profit_factor if report.profit_factor != float("inf") else 0.0
            results[s].append(OptimResult(params=params, report=report, score=score, strategy_id=s))

        if idx % 10 == 0 or idx == total:
            logger.info(
                f"  [{idx}/{total}] "
                f"atr={params.atr_ratio} vol={params.vol_mult} "
                f"tail={params.hammer_tail} body={params.hammer_body} 완료"
            )

    for s in strategies:
        results[s].sort(key=lambda r: r.score, reverse=True)
    return results



def print_top_results(results: list[OptimResult], top_n: int = 5) -> None:
    print(f"\n{'='*60}")
    print(f"  Grid Search 결과 상위 {top_n}개")
    print(f"{'='*60}")
    for rank, r in enumerate(results[:top_n], 1):
        row = r.summary_row()
        print(
            f"  [{rank}] atr={row['atr_ratio']} vol={row['vol_mult']} "
            f"tail={row['hammer_tail']} body={row['hammer_body']}"
        )
        print(
            f"       거래={row['trades']}  승률={row['win_rate']}%  "
            f"PF={row['pf']}  MDD={row['mdd']}%  샤프={row['sharpe']}"
        )
    print(f"{'='*60}")
