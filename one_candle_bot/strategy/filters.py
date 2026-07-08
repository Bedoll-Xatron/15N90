"""
2단계: 전략 필터 모듈

- ATR 33% 룰
- 거래량 필터
- 시장 방향성 필터
"""
import logging
from dataclasses import dataclass
from enum import Enum

from config import STRATEGY

logger = logging.getLogger(__name__)


class Direction(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str


@dataclass(frozen=True)
class MarketDirectionResult:
    long_allowed: bool
    short_allowed: bool

    def allows(self, direction: Direction) -> bool:
        if direction == Direction.LONG:
            return self.long_allowed
        return self.short_allowed

    @property
    def any_allowed(self) -> bool:
        return self.long_allowed or self.short_allowed


# ------------------------------------------------------------------ #
#  ATR 33% 필터                                                       #
# ------------------------------------------------------------------ #

def check_atr_filter(
    box_size: float,
    atr: float,
    ratio: float = STRATEGY.atr_ratio,
) -> FilterResult:
    """
    15분봉 범위 >= ATR * ratio 검증

    박스 크기가 충분히 커야 세력 개입(개미 털기)으로 인정.
    기본 ratio = 0.33 (33%)
    """
    if atr <= 0:
        return FilterResult(passed=False, reason=f"ATR 값 이상 (atr={atr})")

    actual = box_size / atr
    passed = actual >= ratio

    msg = (
        f"박스 {box_size:,.0f} / ATR {atr:,.0f} = {actual:.1%} "
        f"(기준 {ratio:.0%})"
    )
    logger.debug(f"ATR 필터: {msg} → {'통과' if passed else '탈락'}")

    return FilterResult(
        passed=passed,
        reason=msg,
    )


# ------------------------------------------------------------------ #
#  거래량 필터                                                         #
# ------------------------------------------------------------------ #

def check_volume_filter(
    volume_15m: int,
    avg_daily_volume: float,
    multiplier: float = STRATEGY.volume_multiplier,
) -> FilterResult:
    """
    15분봉 거래량 >= 일평균 거래량 * multiplier 검증

    거래량 폭발이 없으면 세력 개입이 아닌 자연 진동으로 판단.
    기본 multiplier = 1.5 (150%)
    """
    if avg_daily_volume <= 0:
        return FilterResult(passed=False, reason="일평균 거래량 데이터 없음")

    threshold = avg_daily_volume * multiplier
    passed = volume_15m >= threshold

    msg = (
        f"15분봉 거래량 {volume_15m:,} / "
        f"임계 {threshold:,.0f} (평균 {avg_daily_volume:,.0f} × {multiplier})"
    )
    logger.debug(f"거래량 필터: {msg} → {'통과' if passed else '탈락'}")

    return FilterResult(passed=passed, reason=msg)


# ------------------------------------------------------------------ #
#  시장 방향성 필터                                                    #
# ------------------------------------------------------------------ #

def check_market_direction(
    kospi_change_pct: float,
    kosdaq_change_pct: float,
    threshold_pct: float = STRATEGY.market_filter_pct,
) -> MarketDirectionResult:
    """
    KOSPI/KOSDAQ 전일 대비 등락률로 허용 방향 결정

    - 하락장 (-threshold% 이하): Long 금지
    - 상승장 (+threshold% 이상): Short 금지
    - 두 지수 중 하나라도 해당하면 적용
    """
    long_allowed  = True
    short_allowed = True

    worst = min(kospi_change_pct, kosdaq_change_pct)
    best  = max(kospi_change_pct, kosdaq_change_pct)

    if worst <= -threshold_pct:
        long_allowed = False
        logger.debug(
            f"시장 필터: LONG 금지 "
            f"(KOSPI {kospi_change_pct:+.2f}%, KOSDAQ {kosdaq_change_pct:+.2f}%)"
        )

    if best >= threshold_pct:
        short_allowed = False
        logger.debug(
            f"시장 필터: SHORT 금지 "
            f"(KOSPI {kospi_change_pct:+.2f}%, KOSDAQ {kosdaq_change_pct:+.2f}%)"
        )

    return MarketDirectionResult(
        long_allowed=long_allowed,
        short_allowed=short_allowed,
    )


# ------------------------------------------------------------------ #
#  종합 판단                                                           #
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class StockSignal:
    stock_code: str
    atr: float
    box_high: float
    box_low: float
    box_size: float
    atr_filter: FilterResult
    volume_filter: FilterResult
    market_direction: MarketDirectionResult

    @property
    def tradeable(self) -> bool:
        return (
            self.atr_filter.passed
            and self.volume_filter.passed
            and self.market_direction.any_allowed
        )

    def summary(self) -> str:
        lines = [
            f"[{self.stock_code}]",
            f"  박스: {self.box_low:,.0f} ~ {self.box_high:,.0f}  (크기 {self.box_size:,.0f})",
            f"  ATR 필터 : {'✓' if self.atr_filter.passed else '✗'}  {self.atr_filter.reason}",
            f"  거래량   : {'✓' if self.volume_filter.passed else '✗'}  {self.volume_filter.reason}",
            f"  Long 허용: {'✓' if self.market_direction.long_allowed else '✗'}",
            f"  Short 허용: {'✓' if self.market_direction.short_allowed else '✗'}",
            f"  → 매매 가능: {'YES' if self.tradeable else 'NO'}",
        ]
        return "\n".join(lines)
