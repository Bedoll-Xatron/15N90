"""
3단계 단위 테스트 - API 없이 순수 패턴 로직만 검증
실행: python -m pytest tests/test_step3.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market.data_processor import BoxRange, Candle
from strategy.pattern import (
    is_hammer, is_shooting_star,
    is_bullish_engulfing, is_bearish_engulfing,
    detect_entry_signal,
    PatternType, EntryType, EntrySignal,
)
from strategy.filters import Direction


def c(o, h, l, cl, t="091500") -> Candle:
    """테스트용 캔들 생성 헬퍼"""
    return Candle(time=t, open=o, high=h, low=l, close=cl, volume=10000)


def box(high, low) -> BoxRange:
    return BoxRange(high=high, low=low)


# ================================================================== #
#  망치형(Hammer) 테스트                                              #
# ================================================================== #

class TestHammer:
    def test_classic_hammer(self):
        """아래꼬리 70%, 몸통 10%, 윗꼬리 0% → 전형적 망치형"""
        candle = c(o=970, h=980, l=900, cl=980)
        # total=80, body=10(12.5%), lower=70(87.5%), upper=0
        assert is_hammer(candle)

    def test_doji_hammer(self):
        """몸통=0인 도지 망치형"""
        candle = c(o=970, h=972, l=900, cl=970)
        # total=72, body=0, lower=70(97%), upper=2(2.8%)
        assert is_hammer(candle)

    def test_fail_body_too_large(self):
        """몸통이 너무 크면 탈락"""
        candle = c(o=950, h=960, l=900, cl=960)
        # total=60, body=10(16.7%), lower=50(83.3%), upper=0
        # → body 비율이 16.7%로 25% 이하 → 통과할 수 있음
        # 더 명확하게 몸통 40% 캔들로 테스트
        candle2 = c(o=940, h=960, l=900, cl=960)
        # total=60, body=20(33%), lower=40(67%), upper=0
        assert not is_hammer(candle2)

    def test_fail_lower_wick_too_short(self):
        """아래꼬리가 짧으면 탈락"""
        candle = c(o=950, h=960, l=948, cl=960)
        # total=12, body=10(83%), lower=2(17%) → 꼬리 비율 부족
        assert not is_hammer(candle)

    def test_fail_upper_wick_too_large(self):
        """윗꼬리가 크면 탈락 (역망치형에 해당)"""
        candle = c(o=910, h=980, l=900, cl=912)
        # total=80, upper=68(85%) → 망치형 아님
        assert not is_hammer(candle)

    def test_fail_zero_range(self):
        """범위 0 캔들 → 탈락"""
        candle = c(o=100, h=100, l=100, cl=100)
        assert not is_hammer(candle)


# ================================================================== #
#  역망치형(Shooting Star) 테스트                                     #
# ================================================================== #

class TestShootingStar:
    def test_classic_shooting_star(self):
        """윗꼬리 70%, 몸통 10%, 아래꼬리 0% → 전형적 역망치형"""
        candle = c(o=910, h=980, l=900, cl=912)
        # total=80, upper=68(85%), body=2(2.5%), lower=10(12.5%)
        # upper 85% >= 60%, body 2.5% <= 25%, lower 12.5% <= 15% → 통과
        assert is_shooting_star(candle)

    def test_fail_lower_wick_too_large(self):
        """아래꼬리가 크면 탈락"""
        candle = c(o=970, h=980, l=900, cl=980)
        # 망치형이지, 역망치형이 아님
        assert not is_shooting_star(candle)

    def test_fail_upper_wick_too_short(self):
        """윗꼬리가 짧으면 탈락"""
        candle = c(o=950, h=960, l=948, cl=950)
        # total=12, upper=10(83%), body=0, lower=2(17%) → lower 17% > 15% 탈락
        assert not is_shooting_star(candle)

    def test_hammer_is_not_shooting_star(self):
        """망치형은 역망치형이 아님"""
        candle = c(o=970, h=980, l=900, cl=975)
        assert is_hammer(candle)
        assert not is_shooting_star(candle)


# ================================================================== #
#  상승 장악형(Bullish Engulfing) 테스트                              #
# ================================================================== #

class TestBullishEngulfing:
    def test_classic_bullish_engulfing(self):
        """전형적인 상승 장악형"""
        prev = c(o=1000, h=1010, l=980, cl=985)  # 음봉
        curr = c(o=982,  h=1020, l=975, cl=1015)  # 양봉, 완전 포함
        assert is_bullish_engulfing(curr, prev)

    def test_fail_both_bullish(self):
        """둘 다 양봉이면 탈락"""
        prev = c(o=980, h=1010, l=975, cl=1000)
        curr = c(o=995, h=1030, l=990, cl=1025)
        assert not is_bullish_engulfing(curr, prev)

    def test_fail_not_fully_engulfed(self):
        """현재 종가가 직전 시가를 못 넘으면 탈락"""
        prev = c(o=1000, h=1010, l=980, cl=985)  # 음봉, 시가=1000
        curr = c(o=982,  h=1010, l=975, cl=998)   # 종가=998 < prev.open=1000
        assert not is_bullish_engulfing(curr, prev)

    def test_exact_boundary(self):
        """경계값: 현재 종가 == 직전 시가 → 통과"""
        prev = c(o=1000, h=1010, l=980, cl=985)
        curr = c(o=984,  h=1010, l=975, cl=1000)  # cl == prev.open
        assert is_bullish_engulfing(curr, prev)


# ================================================================== #
#  하락 장악형(Bearish Engulfing) 테스트                              #
# ================================================================== #

class TestBearishEngulfing:
    def test_classic_bearish_engulfing(self):
        """전형적인 하락 장악형"""
        prev = c(o=985,  h=1020, l=980, cl=1010)  # 양봉
        curr = c(o=1012, h=1025, l=975, cl=982)   # 음봉, 완전 포함
        assert is_bearish_engulfing(curr, prev)

    def test_fail_both_bearish(self):
        prev = c(o=1000, h=1010, l=980, cl=985)
        curr = c(o=983,  h=995,  l=970, cl=975)
        assert not is_bearish_engulfing(curr, prev)

    def test_fail_not_fully_engulfed(self):
        """현재 종가가 직전 시가보다 높으면 탈락"""
        prev = c(o=985, h=1020, l=980, cl=1010)  # 양봉, 시가=985
        curr = c(o=1012, h=1025, l=988, cl=990)  # 종가=990 > prev.open=985
        assert not is_bearish_engulfing(curr, prev)


# ================================================================== #
#  detect_entry_signal 통합 테스트                                    #
# ================================================================== #

class TestDetectEntrySignal:
    def _box(self):
        return box(high=10500, low=10000)

    # ── Long 신호 ──

    def test_hammer_long_signal(self):
        """박스 하방 이탈 + 망치형 → Long TRIGGER 신호"""
        # low=9900 < box.low=10000, 망치형
        candle = c(o=10300, h=10350, l=9900, cl=10320)
        # total=450, body=20(4.4%), lower=400(88.9%), upper=30(6.7%) → 망치형
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is not None
        assert sig.direction == Direction.LONG
        assert sig.pattern == PatternType.HAMMER
        assert sig.entry_type == EntryType.TRIGGER
        assert sig.trigger_price == candle.high
        assert sig.stop_loss < candle.low
        assert sig.take_profit == self._box().high

    def test_bullish_engulfing_long_signal(self):
        """박스 하방 이탈 후 상승 장악형 → Long IMMEDIATE 신호"""
        prev = c(o=10050, h=10080, l=9800, cl=9850)  # 음봉, 박스 하방 이탈
        curr = c(o=9840,  h=10200, l=9820, cl=10060) # 양봉, 장악
        sig = detect_entry_signal(curr, prev, self._box())
        assert sig is not None
        assert sig.direction == Direction.LONG
        assert sig.pattern == PatternType.BULLISH_ENGULF
        assert sig.entry_type == EntryType.IMMEDIATE
        assert sig.trigger_price == curr.close

    # ── Short 신호 ──

    def test_shooting_star_short_signal(self):
        """박스 상방 이탈 + 역망치형 → Short TRIGGER 신호"""
        # high=10700 > box.high=10500, 역망치형
        candle = c(o=10450, h=10700, l=10430, cl=10460)
        # total=270, upper=240(88.9%), body=10(3.7%), lower=20(7.4%)
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is not None
        assert sig.direction == Direction.SHORT
        assert sig.pattern == PatternType.SHOOTING_STAR
        assert sig.entry_type == EntryType.TRIGGER
        assert sig.trigger_price == candle.low
        assert sig.stop_loss > candle.high
        assert sig.take_profit == self._box().low

    def test_bearish_engulfing_short_signal(self):
        """박스 상방 이탈 후 하락 장악형 → Short IMMEDIATE 신호"""
        prev = c(o=10450, h=10750, l=10420, cl=10700)  # 양봉, 상방 이탈
        curr = c(o=10710, h=10760, l=10300, cl=10440)  # 음봉, 장악
        sig = detect_entry_signal(curr, prev, self._box())
        assert sig is not None
        assert sig.direction == Direction.SHORT
        assert sig.pattern == PatternType.BEARISH_ENGULF
        assert sig.entry_type == EntryType.IMMEDIATE

    # ── 신호 없음 ──

    def test_no_signal_inside_box(self):
        """박스 내부 캔들 → 신호 없음 (휩소 방지)"""
        candle = c(o=10100, h=10400, l=10050, cl=10200)
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is None

    def test_no_signal_no_pattern(self):
        """박스 이탈했지만 패턴 없음 → 신호 없음"""
        # low < box.low 이지만 일반 음봉
        candle = c(o=10200, h=10250, l=9900, cl=10000)
        # total=350, body=200(57%) → 몸통 너무 큼, 망치형 아님
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is None

    def test_no_signal_bilateral_breakout(self):
        """양방향 동시 돌파 → 신호 없음"""
        candle = c(o=10200, h=10600, l=9900, cl=10300)
        # high > 10500 and low < 10000 동시
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is None

    def test_engulfing_invalid_prev_inside_box(self):
        """직전 캔들이 박스 내부였던 장악형 → 신호 없음"""
        prev = c(o=10300, h=10400, l=10100, cl=10150)  # 박스 내부 음봉
        curr = c(o=10140, h=10400, l=10080, cl=10350)  # 양봉, 장악
        # curr.low=10080 < box.low=10000 → False, curr.low >= box.low
        sig = detect_entry_signal(curr, prev, self._box())
        # curr.low=10080 >= box.low=10000 → broke_down=False → 신호 없음
        assert sig is None

    # ── 손익비 검증 ──

    def test_rr_ratio_positive(self):
        """손익비가 0보다 커야 함"""
        candle = c(o=10300, h=10350, l=9900, cl=10320)
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is not None
        assert sig.rr_ratio > 0

    def test_stop_loss_below_entry_for_long(self):
        """Long: 손절선 < 진입가"""
        candle = c(o=10300, h=10350, l=9900, cl=10320)
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is not None
        assert sig.stop_loss < sig.trigger_price

    def test_stop_loss_above_entry_for_short(self):
        """Short: 손절선 > 진입가"""
        candle = c(o=10450, h=10700, l=10430, cl=10460)
        sig = detect_entry_signal(candle, None, self._box())
        assert sig is not None
        assert sig.stop_loss > sig.trigger_price
