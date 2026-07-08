"""
2단계 단위 테스트 - API 없이 순수 로직만 검증
실행: python -m pytest tests/test_step2.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market.data_processor import (
    calc_atr,
    parse_minute_candles,
    aggregate_to_15m,
    get_first_15m_candle,
    candle_to_box,
    calc_avg_daily_volume,
    Candle,
)
from strategy.filters import (
    check_atr_filter,
    check_volume_filter,
    check_market_direction,
    Direction,
)


# ------------------------------------------------------------------ #
#  ATR 계산 테스트                                                    #
# ------------------------------------------------------------------ #

def _make_daily_row(high, low, close):
    return {"stck_hgpr": str(high), "stck_lwpr": str(low), "stck_clpr": str(close)}


def test_atr_simple():
    """TR = High - Low 일 때 ATR = TR들의 평균"""
    rows = [_make_daily_row(110, 90, 100)] * 15  # 15일치
    atr = calc_atr(rows, period=14)
    assert atr == 20.0, f"expected 20.0, got {atr}"


def test_atr_uses_prev_close():
    """갭이 클 때 TR = max(H-L, |H-PC|, |L-PC|) 사용 확인"""
    rows = [
        _make_daily_row(105, 95, 100),  # 최신
        _make_daily_row(50,  40,  80),  # 전일 종가 80
    ] + [_make_daily_row(100, 90, 95)] * 13
    atr = calc_atr(rows, period=1)
    # TR: max(105-95=10, |105-80|=25, |95-80|=15) = 25
    assert atr == 25.0


def test_atr_insufficient_data():
    rows = [_make_daily_row(100, 90, 95)] * 10
    try:
        calc_atr(rows, period=14)
        assert False, "예외가 발생해야 함"
    except ValueError:
        pass


# ------------------------------------------------------------------ #
#  분봉 파싱 / 15분봉 집계 테스트                                     #
# ------------------------------------------------------------------ #

def _make_minute_row(hhmmss, o, h, l, c, vol=1000):
    return {
        "stck_cntg_hour": hhmmss,
        "stck_oprc": str(o), "stck_hgpr": str(h),
        "stck_lwpr": str(l), "stck_clpr": str(c),
        "cntg_vol": str(vol),
    }


def test_parse_minute_candles_order():
    """KIS는 최신순 → 파싱 후 오래된 순이어야 함"""
    raw = [
        _make_minute_row("091500", 100, 105, 98, 103),  # 최신
        _make_minute_row("091400", 99,  104, 97, 100),
        _make_minute_row("090100", 95,  100, 94, 99),   # 오래된
    ]
    candles = parse_minute_candles(raw)
    assert candles[0].time == "090100"
    assert candles[-1].time == "091500"


def test_get_first_15m_candle():
    """09:00~09:15 구간 집계 확인"""
    raw = [
        _make_minute_row("091400", 100, 110, 95,  105, 500),  # KIS 최신순
        _make_minute_row("090500", 100, 108, 96,  104, 300),
        _make_minute_row("090100", 100, 106, 97,  103, 200),
    ]
    candles = parse_minute_candles(raw)
    c15 = get_first_15m_candle(candles)

    assert c15 is not None
    assert c15.high == 110
    assert c15.low == 95
    assert c15.volume == 1000  # 500+300+200


def test_get_first_15m_candle_empty():
    """09:00~09:15 데이터 없으면 None"""
    raw = [_make_minute_row("091600", 100, 105, 98, 103)]
    candles = parse_minute_candles(raw)
    assert get_first_15m_candle(candles) is None


def test_aggregate_to_15m():
    """15분 단위 집계 확인"""
    raw = [
        _make_minute_row("091400", 103, 109, 100, 107),  # 09:00 슬롯
        _make_minute_row("090800", 101, 106, 99,  104),  # 09:00 슬롯
        _make_minute_row("090100", 100, 105, 98,  103),  # 09:00 슬롯
        _make_minute_row("091600", 108, 112, 106, 111),  # 09:15 슬롯
    ]
    candles = parse_minute_candles(raw)
    result = aggregate_to_15m(candles)

    assert len(result) == 2
    slot_0900 = result[0]
    assert slot_0900.open == 100
    assert slot_0900.high == 109
    assert slot_0900.low  == 98
    assert slot_0900.close == 107


# ------------------------------------------------------------------ #
#  거래량 통계 테스트                                                  #
# ------------------------------------------------------------------ #

def test_calc_avg_daily_volume():
    rows = [{"acml_vol": "1000000"}, {"acml_vol": "2000000"}, {"acml_vol": "3000000"}]
    avg = calc_avg_daily_volume(rows, period=3)
    assert avg == 2_000_000.0


# ------------------------------------------------------------------ #
#  ATR 필터 테스트                                                     #
# ------------------------------------------------------------------ #

def test_atr_filter_pass():
    result = check_atr_filter(box_size=5000, atr=10000, ratio=0.33)
    assert result.passed  # 5000/10000=50% >= 33%


def test_atr_filter_fail():
    result = check_atr_filter(box_size=2000, atr=10000, ratio=0.33)
    assert not result.passed  # 2000/10000=20% < 33%


def test_atr_filter_zero_atr():
    result = check_atr_filter(box_size=5000, atr=0)
    assert not result.passed


# ------------------------------------------------------------------ #
#  거래량 필터 테스트                                                  #
# ------------------------------------------------------------------ #

def test_volume_filter_pass():
    result = check_volume_filter(volume_15m=200_000, avg_daily_volume=100_000, multiplier=1.5)
    assert result.passed  # 200k >= 150k


def test_volume_filter_fail():
    result = check_volume_filter(volume_15m=100_000, avg_daily_volume=100_000, multiplier=1.5)
    assert not result.passed  # 100k < 150k


def test_volume_filter_zero_avg():
    result = check_volume_filter(volume_15m=100_000, avg_daily_volume=0)
    assert not result.passed


# ------------------------------------------------------------------ #
#  시장 방향성 필터 테스트                                             #
# ------------------------------------------------------------------ #

def test_market_direction_neutral():
    """±1% 이내 → Long/Short 모두 허용"""
    r = check_market_direction(0.5, 0.3)
    assert r.long_allowed and r.short_allowed


def test_market_direction_block_long():
    """KOSPI -1.5% → Long 금지"""
    r = check_market_direction(-1.5, 0.2)
    assert not r.long_allowed
    assert r.short_allowed


def test_market_direction_block_short():
    """KOSDAQ +1.2% → Short 금지"""
    r = check_market_direction(0.3, 1.2)
    assert r.long_allowed
    assert not r.short_allowed


def test_market_direction_both_blocked():
    """극단적 발산 시 → 비정상 상황 (둘 다 금지 가능성 낮지만 로직 검증)"""
    r = check_market_direction(-2.0, 2.0)
    assert not r.long_allowed
    assert not r.short_allowed
    assert not r.any_allowed


def test_direction_allows():
    r = check_market_direction(-1.5, 0.2)
    assert not r.allows(Direction.LONG)
    assert r.allows(Direction.SHORT)
