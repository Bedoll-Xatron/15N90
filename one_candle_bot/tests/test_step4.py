"""
4단계 단위 테스트 — 포지션 사이저
실행: python -m pytest tests/test_step4.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from strategy.position_sizer import PositionSizer, calc_position_size, PositionSize


# ================================================================== #
#  기본 계산 검증                                                      #
# ================================================================== #

class TestBasicCalc:

    def test_long_risk_based(self):
        """Long: 리스크 기반 수량 — max_invest 상한이 걸리지 않는 저가 종목"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        # risk = 100,000원 / stop_gap = 5,000-4,000=1,000원 → 100주
        # max_invest = 2,000,000 / 5,000 = 400주 → 상한 안 걸림
        result = ps.calc(entry_price=5_000, stop_loss=4_000, take_profit=8_000)
        assert result.shares == 100

    def test_long_cap_based(self):
        """Long: max_invest 상한이 리스크 기반보다 먼저 걸리는 고가 종목"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01, max_invest_pct=0.20)
        # risk = 100,000 / stop_gap = 1,000 → 100주 요구
        # max_invest = 2,000,000 / 50,000 = 40주 → 상한 적용
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.shares == 40

    def test_short_basic(self):
        """Short: 손절이 진입가보다 위, 리스크 기반"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        # stop_gap = 6,000-5,000=1,000 → 100주
        result = ps.calc(entry_price=5_000, stop_loss=6_000, take_profit=2_000)
        assert result.shares == 100

    def test_shares_floor_not_ceil(self):
        """소수점 주식 수는 내림 처리"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        # risk = 100,000 / stop_gap = 5,000-3,500=1,500 → 66.66 → 66주
        # max_invest = 2,000,000 / 5,000 = 400주 → 상한 안 걸림
        result = ps.calc(entry_price=5_000, stop_loss=3_500, take_profit=9_500)
        assert result.shares == 66

    def test_minimum_one_share(self):
        """손절폭이 너무 커도 최소 1주"""
        ps = PositionSizer(equity=100_000, risk_pct=0.01)
        # risk = 1,000, stop_gap = 50,000 → 0.02 → floor=0 → min=1
        result = ps.calc(entry_price=100_000, stop_loss=50_000, take_profit=200_000)
        assert result.shares == 1

    def test_max_invest_cap(self):
        """투자금 상한 (20%)이 리스크 기반 수량보다 먼저 걸릴 때"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01, max_invest_pct=0.20)
        # max_invest = 2,000,000 / 100,000원 = 20주
        # risk 기준 = 100,000 / 100 = 1,000주  → 상한 20주 적용
        result = ps.calc(entry_price=100_000, stop_loss=99_900, take_profit=105_000)
        assert result.shares == 20

    def test_invest_amount(self):
        """투자 금액 = 수량 × 진입가"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.invest_amount == result.shares * result.entry_price

    def test_risk_amount(self):
        """실제 리스크 금액 = 수량 × 손절폭"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.risk_amount == result.shares * result.stop_gap


# ================================================================== #
#  손익비(RR) 계산                                                     #
# ================================================================== #

class TestRRRatio:

    def test_rr_3to1(self):
        """손익비 3:1"""
        ps = PositionSizer(equity=10_000_000)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        # profit_gap=3,000, stop_gap=1,000 → RR=3.0
        assert result.rr_ratio == 3.0

    def test_rr_2to1(self):
        ps = PositionSizer(equity=10_000_000)
        result = ps.calc(entry_price=50_000, stop_loss=48_000, take_profit=54_000)
        # profit=4,000, stop=2,000 → RR=2.0
        assert result.rr_ratio == 2.0

    def test_expected_profit_gt_expected_loss(self):
        """손익비 > 1 이면 기대수익 > 기대손실"""
        ps = PositionSizer(equity=10_000_000)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.expected_profit > result.expected_loss


# ================================================================== #
#  유효성 검사                                                         #
# ================================================================== #

class TestValidation:

    def test_invalid_equity_zero(self):
        with pytest.raises(ValueError, match="equity"):
            PositionSizer(equity=0)

    def test_invalid_equity_negative(self):
        with pytest.raises(ValueError):
            PositionSizer(equity=-1_000_000)

    def test_invalid_risk_pct_too_high(self):
        with pytest.raises(ValueError, match="risk_pct"):
            PositionSizer(equity=10_000_000, risk_pct=0.10)  # 10% 초과

    def test_invalid_risk_pct_zero(self):
        with pytest.raises(ValueError):
            PositionSizer(equity=10_000_000, risk_pct=0)

    def test_entry_equals_stop(self):
        ps = PositionSizer(equity=10_000_000)
        with pytest.raises(ValueError, match="같습니다"):
            ps.calc(entry_price=50_000, stop_loss=50_000, take_profit=53_000)

    def test_long_tp_below_entry(self):
        """Long인데 익절가가 진입가보다 낮음"""
        ps = PositionSizer(equity=10_000_000)
        with pytest.raises(ValueError, match="Long"):
            ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=49_500)

    def test_short_tp_above_entry(self):
        """Short인데 익절가가 진입가보다 높음"""
        ps = PositionSizer(equity=10_000_000)
        with pytest.raises(ValueError, match="Short"):
            ps.calc(entry_price=50_000, stop_loss=51_000, take_profit=51_500)

    def test_zero_price(self):
        ps = PositionSizer(equity=10_000_000)
        with pytest.raises(ValueError, match="0보다"):
            ps.calc(entry_price=0, stop_loss=49_000, take_profit=53_000)


# ================================================================== #
#  리스크 비율 범위 확인                                               #
# ================================================================== #

class TestRiskControl:

    def test_actual_risk_pct_within_limit(self):
        """실제 리스크 비율이 설정값을 초과하지 않음"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.risk_pct <= 0.01

    def test_risk_pct_2pct(self):
        ps = PositionSizer(equity=10_000_000, risk_pct=0.02)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.risk_pct <= 0.02

    def test_invest_within_max(self):
        """투자 금액이 최대 투자 비율 내"""
        equity = 10_000_000
        max_invest_pct = 0.20
        ps = PositionSizer(equity=equity, max_invest_pct=max_invest_pct)
        result = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        assert result.invest_amount <= equity * max_invest_pct


# ================================================================== #
#  편의 함수 테스트                                                    #
# ================================================================== #

class TestConvenienceFunction:

    def test_calc_position_size_same_result(self):
        """편의 함수와 클래스가 동일한 결과"""
        ps = PositionSizer(equity=10_000_000, risk_pct=0.01)
        expected = ps.calc(entry_price=50_000, stop_loss=49_000, take_profit=53_000)
        result = calc_position_size(
            equity=10_000_000,
            entry_price=50_000,
            stop_loss=49_000,
            take_profit=53_000,
            risk_pct=0.01,
        )
        assert result.shares == expected.shares
        assert result.risk_amount == expected.risk_amount


# ================================================================== #
#  summary() 출력 확인                                                 #
# ================================================================== #

class TestSummary:

    def test_summary_contains_key_fields(self):
        """저가 종목으로 리스크 기반 100주 확인"""
        ps = PositionSizer(equity=10_000_000)
        result = ps.calc(entry_price=5_000, stop_loss=4_000, take_profit=8_000)
        text = result.summary()
        assert "100" in text      # 수량
        assert "5,000" in text    # 진입가
        assert "4,000" in text    # 손절선
        assert "8,000" in text    # 익절선
        assert "3.0" in text      # 손익비 (profit=3000, stop=1000)
