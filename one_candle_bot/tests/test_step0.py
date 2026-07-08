"""
0단계 단위 테스트 — pykrx 없이 합성 데이터로 엔진/리포트 검증
실행: python -m pytest tests/test_step0.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from backtest.engine import BacktestParams, Trade, simulate_one_stock, _simulate_exit
from backtest.report import BacktestReport, _calc_mdd, _calc_sharpe
from strategy.filters import Direction


# ------------------------------------------------------------------ #
#  합성 데이터 헬퍼                                                    #
# ------------------------------------------------------------------ #

def _make_ohlcv(rows: list[tuple]) -> pd.DataFrame:
    """(open, high, low, close, volume, change_pct) 튜플 리스트 → DataFrame"""
    idx = pd.date_range("2024-01-02", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=idx,
        columns=["open","high","low","close","volume","change_pct"])


def _flat_market(n: int, kospi=0.3, kosdaq=0.2) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    return pd.DataFrame({"kospi_chg": kospi, "kosdaq_chg": kosdaq}, index=idx)


def _base_rows(n: int = 20, o=10000, h=10500, l=9800, c=10200, vol=1_000_000) -> list[tuple]:
    return [(o, h, l, c, vol, 0.5)] * n


# ================================================================== #
#  _simulate_exit 테스트                                              #
# ================================================================== #

class TestSimulateExit:
    def _row(self, h, l, c) -> pd.Series:
        return pd.Series({"open": c, "high": h, "low": l, "close": c, "volume": 100, "change_pct": 0})

    def test_long_tp_hit(self):
        p, r = _simulate_exit(Direction.LONG, 10000, 9800, 10500,
                              self._row(h=10600, l=9900, c=10400))
        assert p == 10500 and r == "TP"

    def test_long_sl_hit(self):
        p, r = _simulate_exit(Direction.LONG, 10000, 9800, 10500,
                              self._row(h=10200, l=9700, c=10100))
        assert p == 9800 and r == "SL"

    def test_long_both_hit_sl_first(self):
        """TP와 SL 동시 → SL 우선 (보수적)"""
        p, r = _simulate_exit(Direction.LONG, 10000, 9800, 10500,
                              self._row(h=10600, l=9700, c=10200))
        assert p == 9800 and r == "SL"

    def test_long_close(self):
        p, r = _simulate_exit(Direction.LONG, 10000, 9800, 10500,
                              self._row(h=10300, l=9900, c=10100))
        assert p == 10100 and r == "CLOSE"

    def test_short_tp_hit(self):
        p, r = _simulate_exit(Direction.SHORT, 10000, 10200, 9500,
                              self._row(h=10100, l=9400, c=9600))
        assert p == 9500 and r == "TP"

    def test_short_sl_hit(self):
        p, r = _simulate_exit(Direction.SHORT, 10000, 10200, 9500,
                              self._row(h=10300, l=9600, c=9800))
        assert p == 10200 and r == "SL"

    def test_short_close(self):
        p, r = _simulate_exit(Direction.SHORT, 10000, 10200, 9500,
                              self._row(h=10100, l=9600, c=9900))
        assert p == 9900 and r == "CLOSE"


# ================================================================== #
#  BacktestReport 테스트                                              #
# ================================================================== #

def _make_trade(pnl: float, exit_reason="TP", direction="LONG") -> Trade:
    entry = 10000.0
    if direction == "LONG":
        exit_p = entry + pnl
        tp = entry + 500
        sl = entry - 200
    else:
        exit_p = entry - pnl
        tp = entry - 500
        sl = entry + 200
    return Trade(
        date="2024-01-02", ticker="TEST",
        direction=direction, pattern="HAMMER",
        entry_price=entry, stop_loss=sl, take_profit=tp,
        exit_price=exit_p, exit_reason=exit_reason,
    )


class TestBacktestReport:

    def test_empty_trades(self):
        r = BacktestReport.from_trades([])
        assert r.total_trades == 0
        assert r.win_rate == 0.0

    def test_win_rate(self):
        trades = [_make_trade(500)] * 6 + [_make_trade(-200)] * 4
        r = BacktestReport.from_trades(trades)
        assert r.win_rate == 60.0
        assert r.wins == 6
        assert r.losses == 4

    def test_profit_factor(self):
        trades = [_make_trade(300)] * 3 + [_make_trade(-100)] * 3
        r = BacktestReport.from_trades(trades)
        # PF = 900 / 300 = 3.0
        assert abs(r.profit_factor - 3.0) < 0.01

    def test_profit_factor_no_loss(self):
        trades = [_make_trade(500)] * 3
        r = BacktestReport.from_trades(trades)
        assert r.profit_factor == float("inf")

    def test_total_pnl(self):
        trades = [_make_trade(500)] * 2 + [_make_trade(-200)] * 2
        r = BacktestReport.from_trades(trades)
        assert r.total_pnl == 600.0

    def test_exit_reason_counts(self):
        trades = [
            _make_trade(300, "TP"),
            _make_trade(-100, "SL"),
            _make_trade(50,  "CLOSE"),
        ]
        r = BacktestReport.from_trades(trades)
        assert r.tp_count == 1
        assert r.sl_count == 1
        assert r.close_count == 1


class TestMDD:

    def test_mdd_no_drawdown(self):
        pnl = [100, 200, 300]
        assert _calc_mdd(pnl, 10_000) == 0.0

    def test_mdd_single_drop(self):
        # equity: 10000 → 10100 → 9600 → 9700
        pnl = [100, -500, 100]
        mdd = _calc_mdd(pnl, 10_000)
        # peak=10100, min=9600 → dd = 500/10100 ≈ 4.95%
        assert 4.0 < mdd < 6.0

    def test_mdd_all_losses(self):
        pnl = [-100, -200, -300]
        mdd = _calc_mdd(pnl, 10_000)
        # equity: 9900 → 9700 → 9400 → dd = 600/10000 = 6%
        assert mdd > 0


class TestSharpe:

    def test_sharpe_zero_std(self):
        assert _calc_sharpe([100, 100, 100]) == 0.0

    def test_sharpe_positive(self):
        # 모두 양수 수익 → 양의 샤프
        pnl = [100, 120, 110, 130, 105]
        assert _calc_sharpe(pnl) > 0

    def test_sharpe_negative(self):
        pnl = [-100, -120, -110, -90, -130]
        assert _calc_sharpe(pnl) < 0


# ================================================================== #
#  simulate_one_stock 통합 테스트                                     #
# ================================================================== #

class TestSimulateOneStock:

    def _params(self, **kwargs) -> BacktestParams:
        p = BacktestParams()
        for k, v in kwargs.items():
            object.__setattr__(p, k, v)
        return p

    def test_returns_list(self):
        rows = _base_rows(25)
        ohlcv = _make_ohlcv(rows)
        market = _flat_market(25)
        params = BacktestParams()
        result = simulate_one_stock(ohlcv, market, "TEST", params)
        assert isinstance(result, list)

    def test_insufficient_data(self):
        """데이터 부족 시 빈 리스트"""
        rows = _base_rows(5)
        ohlcv = _make_ohlcv(rows)
        market = _flat_market(5)
        result = simulate_one_stock(ohlcv, market, "TEST", BacktestParams())
        assert result == []

    def test_hammer_long_signal_detected(self):
        """망치형 Long 신호가 있는 합성 데이터"""
        # 15일 베이스 + 1일 박스 기준일(고가=10500, 저가=10000)
        # + 1일 신호일(저가<10000이고 망치형) + 1일 청산일
        base = _base_rows(16, o=10200, h=10500, l=10000, c=10300, vol=500_000)
        # 박스 기준일: 전일 고가=10500, 저가=10000
        box_day = (10200, 10500, 10000, 10300, 600_000, 0.5)
        # 신호일: low=9700(박스 하방이탈), 망치형
        # total=800, lower_wick=300(37.5%)... 더 명확한 망치형 필요
        # open=10290, high=10310, low=9700, close=10300
        # total=610, body=10(1.6%), lower=590(96.7%), upper=10(1.6%) → 망치형
        sig_day = (10290, 10310, 9700, 10300, 2_000_000, -1.0)
        # 익절일: high > box_high(10500)
        exit_day = (10300, 10600, 10250, 10550, 800_000, 2.0)
        rows = base + [box_day, sig_day, exit_day]
        ohlcv = _make_ohlcv(rows)
        market = _flat_market(len(rows))

        # ATR 필터: box_size = 10500-10000=500, ATR ≈ 500 → ratio=500/500=1.0 >= 0.33 통과
        # 거래량 필터: 2_000_000 vs avg ~500k*1.5=750k → 통과
        params = BacktestParams(atr_ratio=0.1, vol_mult=1.0)  # 느슨한 조건
        trades = simulate_one_stock(ohlcv, market, "TEST", params)

        assert len(trades) >= 1
        long_trades = [t for t in trades if t.direction == "LONG"]
        assert len(long_trades) >= 1

    def test_market_filter_blocks_long(self):
        """KOSPI 하락장에서 Long 신호 차단"""
        base = _base_rows(16, o=10200, h=10500, l=10000, c=10300, vol=500_000)
        box_day = (10200, 10500, 10000, 10300, 600_000, 0.5)
        sig_day = (10290, 10310, 9700, 10300, 2_000_000, -1.0)
        exit_day = (10300, 10600, 10250, 10550, 800_000, 2.0)
        rows = base + [box_day, sig_day, exit_day]
        ohlcv = _make_ohlcv(rows)

        # KOSPI -2% → Long 금지
        market = _flat_market(len(rows), kospi=-2.0, kosdaq=-1.5)
        params = BacktestParams(atr_ratio=0.1, vol_mult=1.0, market_pct=1.0)
        trades = simulate_one_stock(ohlcv, market, "TEST", params)
        long_trades = [t for t in trades if t.direction == "LONG"]
        assert len(long_trades) == 0
