"""
분봉 엔진 단위 테스트 — 실제 CSV 없이 합성 데이터로 검증
실행: python -m pytest tests/test_minute_engine.py -v
"""
import csv
import sys, os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd

from market.data_processor import Candle, aggregate_candles, get_first_15m_candle
from backtest.engine_minute import _simulate_minute_exit
from backtest.minute_loader import load_minute_candles


# ================================================================== #
#  aggregate_candles 테스트                                           #
# ================================================================== #

class TestAggregateCandles:

    def _c(self, time, o, h, l, c, v=1000):
        return Candle(time=time, open=o, high=h, low=l, close=c, volume=v)

    def test_5m_aggregation(self):
        """1분봉 5개 → 5분봉 1개"""
        candles = [
            self._c("091500", 100, 103, 99, 102),
            self._c("091600", 102, 104, 101, 103),
            self._c("091700", 103, 105, 102, 104),
            self._c("091800", 104, 106, 103, 105),
            self._c("091900", 105, 107, 104, 106),
        ]
        result = aggregate_candles(candles, 5)
        assert len(result) == 1
        r = result[0]
        assert r.open  == 100   # 첫 캔들 시가
        assert r.high  == 107   # 최고점
        assert r.low   == 99    # 최저점
        assert r.close == 106   # 마지막 종가
        assert r.volume == 5000

    def test_two_5m_slots(self):
        """09:15~09:19, 09:20~09:24 두 슬롯"""
        candles = [self._c(f"09{15+i:02d}00", 100, 105, 98, 103) for i in range(5)]
        candles += [self._c(f"09{20+i:02d}00", 103, 108, 101, 106) for i in range(5)]
        result = aggregate_candles(candles, 5)
        assert len(result) == 2
        assert result[0].time == "091500"
        assert result[1].time == "092000"

    def test_15m_same_as_existing(self):
        """15분 집계는 aggregate_to_15m 과 동일해야 함"""
        from market.data_processor import aggregate_to_15m
        raw = [
            {"stck_cntg_hour": f"09{i:02d}00", "stck_oprc": "100", "stck_hgpr": "105",
             "stck_lwpr": "98", "stck_clpr": "103", "cntg_vol": "1000"}
            for i in range(1, 16)
        ]
        from market.data_processor import parse_minute_candles
        candles = parse_minute_candles(raw)
        r1 = aggregate_to_15m(candles)
        r2 = aggregate_candles(candles, 15)
        assert len(r1) == len(r2)
        if r1:
            assert r1[0].high  == r2[0].high
            assert r1[0].low   == r2[0].low

    def test_empty_input(self):
        assert aggregate_candles([], 5) == []


# ================================================================== #
#  분봉 청산 시뮬레이션 테스트                                         #
# ================================================================== #

class TestSimulateMinuteExit:

    def _c(self, time, h, l, close):
        return Candle(time=time, open=close, high=h, low=l, close=close, volume=100)

    def test_long_tp(self):
        after = [self._c("093000", h=10600, l=10100, close=10500)]
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, after)
        assert p == 10500 and r == "TP"

    def test_long_sl(self):
        after = [self._c("093000", h=10300, l=9800, close=10000)]
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, after)
        assert p == 9900 and r == "SL"

    def test_long_sl_before_tp(self):
        """손절 먼저 (보수적)"""
        after = [self._c("093000", h=10600, l=9800, close=10200)]
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, after)
        assert r == "SL"

    def test_force_close_at_1459(self):
        after = [self._c("145900", h=10300, l=10100, close=10200)]
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, after)
        assert r == "CLOSE" and p == 10200

    def test_short_tp(self):
        after = [self._c("093000", h=10100, l=9500, close=9600)]
        p, r = _simulate_minute_exit("SHORT", 10000, 10300, 9500, after)
        assert p == 9500 and r == "TP"

    def test_short_sl(self):
        after = [self._c("093000", h=10400, l=9700, close=10000)]
        p, r = _simulate_minute_exit("SHORT", 10000, 10300, 9500, after)
        assert p == 10300 and r == "SL"

    def test_no_candles_returns_entry(self):
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, [])
        assert p == 10200 and r == "CLOSE"

    def test_multiple_candles_until_tp(self):
        """여러 캔들 이후 TP 도달"""
        after = [
            self._c("093100", h=10300, l=10100, close=10200),  # no hit
            self._c("093200", h=10400, l=10150, close=10350),  # no hit
            self._c("093300", h=10550, l=10300, close=10500),  # TP hit
        ]
        p, r = _simulate_minute_exit("LONG", 10200, 9900, 10500, after)
        assert p == 10500 and r == "TP"


# ================================================================== #
#  minute_loader 테스트 (임시 파일)                                   #
# ================================================================== #

class TestMinuteLoader:

    def _write_csv(self, path: Path, rows: list[tuple]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            w.writerows(rows)

    def test_load_basic(self, tmp_path, monkeypatch):
        """CSV 파일 정상 로드"""
        import backtest.minute_loader as ml
        monkeypatch.setattr(ml, "DATA_DIR", tmp_path)

        rows = [
            ("090100", 10000, 10200, 9900, 10100, 5000),
            ("090200", 10100, 10300, 10000, 10200, 4000),
        ]
        csv_path = tmp_path / "005930" / "005930_20240103.csv"
        self._write_csv(csv_path, rows)

        candles = ml.load_minute_candles("005930", "20240103")
        assert len(candles) == 2
        assert candles[0].time == "090100"
        assert candles[0].open == 10000
        assert candles[1].volume == 4000

    def test_load_filters_premarkets(self, tmp_path, monkeypatch):
        """08:xx 프리마켓 캔들 제외"""
        import backtest.minute_loader as ml
        monkeypatch.setattr(ml, "DATA_DIR", tmp_path)

        rows = [
            ("085900", 9950, 10000, 9900, 9980, 100),  # 프리마켓
            ("090100", 10000, 10100, 9900, 10050, 5000),
        ]
        csv_path = tmp_path / "005930" / "005930_20240103.csv"
        self._write_csv(csv_path, rows)

        candles = ml.load_minute_candles("005930", "20240103")
        assert len(candles) == 1
        assert candles[0].time == "090100"

    def test_file_not_found(self, tmp_path, monkeypatch):
        """파일 없으면 빈 리스트"""
        import backtest.minute_loader as ml
        monkeypatch.setattr(ml, "DATA_DIR", tmp_path)
        result = ml.load_minute_candles("005930", "20240103")
        assert result == []

    def test_sorted_output(self, tmp_path, monkeypatch):
        """시간 오름차순 보장"""
        import backtest.minute_loader as ml
        monkeypatch.setattr(ml, "DATA_DIR", tmp_path)

        rows = [  # 역순으로 저장
            ("090300", 100, 105, 98, 103, 1000),
            ("090100", 100, 102, 99, 101, 800),
            ("090200", 101, 104, 100, 102, 900),
        ]
        csv_path = tmp_path / "TEST" / "TEST_20240103.csv"
        self._write_csv(csv_path, rows)

        candles = ml.load_minute_candles("TEST", "20240103")
        times = [c.time for c in candles]
        assert times == sorted(times)

    def test_available_dates(self, tmp_path, monkeypatch):
        import backtest.minute_loader as ml
        monkeypatch.setattr(ml, "DATA_DIR", tmp_path)

        d = tmp_path / "005930"
        d.mkdir()
        for date in ["20240103", "20240104", "20240105"]:
            (d / f"005930_{date}.csv").write_text(
                "time,open,high,low,close,volume\n090100,100,105,98,103,1000"
            )

        dates = ml.available_dates("005930")
        assert dates == ["20240103", "20240104", "20240105"]
