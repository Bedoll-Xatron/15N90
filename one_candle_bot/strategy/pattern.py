"""
3단계: 캔들 패턴 판별 모듈

단일 캔들:  망치형(Hammer) / 역망치형(Shooting Star)
복합 캔들:  상승 장악형(Bullish Engulfing) / 하락 장악형(Bearish Engulfing)
신호 생성: 박스 이탈 여부 + 패턴 → EntrySignal
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config import STRATEGY
from market.data_processor import BoxRange, Candle
from strategy.filters import Direction

logger = logging.getLogger(__name__)

# 한국거래소 호가단위(Tick Size)
def get_tick_size(price: float) -> int:
    if price < 2000: return 1
    if price < 5000: return 5
    if price < 20000: return 10
    if price < 50000: return 50
    if price < 200000: return 100
    if price < 500000: return 500
    return 1000


# ------------------------------------------------------------------ #
#  열거형                                                              #
# ------------------------------------------------------------------ #

class PatternType(str, Enum):
    HAMMER         = "HAMMER"
    SHOOTING_STAR  = "SHOOTING_STAR"
    BULLISH_ENGULF = "BULLISH_ENGULF"
    BEARISH_ENGULF = "BEARISH_ENGULF"
    BREAKOUT       = "BREAKOUT"
    PULLBACK       = "PULLBACK"


class EntryType(str, Enum):
    IMMEDIATE = "IMMEDIATE"  # 종가 즉시 진입 (장악형)
    TRIGGER   = "TRIGGER"    # 트리거 가격 돌파 시 진입 (망치형/역망치형)


# ------------------------------------------------------------------ #
#  진입 신호                                                           #
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class EntrySignal:
    direction:     Direction
    pattern:       PatternType
    entry_type:    EntryType
    trigger_price: float   # IMMEDIATE → 종가, TRIGGER → 돌파 감시 가격
    stop_loss:     float
    take_profit:   float
    candle_time:   str

    @property
    def risk(self) -> float:
        return abs(self.trigger_price - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.take_profit - self.trigger_price)

    @property
    def rr_ratio(self) -> float:
        return round(self.reward / self.risk, 2) if self.risk > 0 else 0.0

    def summary(self) -> str:
        return (
            f"[{self.candle_time}] {self.direction.value} │ {self.pattern.value}"
            f" ({self.entry_type.value})\n"
            f"  진입가: {self.trigger_price:>9,.0f}원\n"
            f"  손절선: {self.stop_loss:>9,.0f}원\n"
            f"  익절선: {self.take_profit:>9,.0f}원\n"
            f"  손익비: {self.rr_ratio:.1f}"
        )


# ------------------------------------------------------------------ #
#  단일 캔들 패턴                                                      #
# ------------------------------------------------------------------ #

def is_hammer(
    candle: Candle,
    tail_ratio: float = STRATEGY.hammer_tail_ratio,
    body_ratio: float = STRATEGY.hammer_body_ratio,
) -> bool:
    """
    망치형(Hammer) 판별
    - 아래꼬리 >= 전체 범위 × tail_ratio  (긴 아래꼬리)
    - 몸통     <= 전체 범위 × body_ratio  (얇은 몸통)
    - 윗꼬리   <= 전체 범위 × 15%        (윗꼬리 거의 없음)
    """
    total = candle.high - candle.low
    if total <= 0:
        return False

    body        = abs(candle.close - candle.open)
    lower_wick  = min(candle.open, candle.close) - candle.low
    upper_wick  = candle.high - max(candle.open, candle.close)

    return (
        lower_wick / total >= tail_ratio
        and body       / total <= body_ratio
        and upper_wick / total <= 0.15
    )


def is_shooting_star(
    candle: Candle,
    tail_ratio: float = STRATEGY.hammer_tail_ratio,
    body_ratio: float = STRATEGY.hammer_body_ratio,
) -> bool:
    """
    역망치형(Shooting Star) 판별 — 망치형의 상하 반전
    - 윗꼬리   >= 전체 범위 × tail_ratio
    - 몸통     <= 전체 범위 × body_ratio
    - 아래꼬리 <= 전체 범위 × 15%
    """
    total = candle.high - candle.low
    if total <= 0:
        return False

    body        = abs(candle.close - candle.open)
    upper_wick  = candle.high - max(candle.open, candle.close)
    lower_wick  = min(candle.open, candle.close) - candle.low

    return (
        upper_wick / total >= tail_ratio
        and body       / total <= body_ratio
        and lower_wick / total <= 0.15
    )


# ------------------------------------------------------------------ #
#  복합 캔들 패턴                                                      #
# ------------------------------------------------------------------ #

def is_bullish_engulfing(curr: Candle, prev: Candle) -> bool:
    """
    상승 장악형(Bullish Engulfing) 판별
    - 직전 캔들: 음봉 (close < open)
    - 현재 캔들: 양봉 (close > open)
    - 현재 양봉 몸통이 직전 음봉 몸통을 완전히 포함
    """
    prev_bearish = prev.close < prev.open
    curr_bullish = curr.close > curr.open

    if not (prev_bearish and curr_bullish):
        return False

    # 현재 시가 <= 직전 종가  and  현재 종가 >= 직전 시가
    return curr.open <= prev.close and curr.close >= prev.open


def is_bearish_engulfing(curr: Candle, prev: Candle) -> bool:
    """
    하락 장악형(Bearish Engulfing) 판별
    - 직전 캔들: 양봉 (close > open)
    - 현재 캔들: 음봉 (close < open)
    - 현재 음봉 몸통이 직전 양봉 몸통을 완전히 포함
    """
    prev_bullish = prev.close > prev.open
    curr_bearish = curr.close < curr.open

    if not (prev_bullish and curr_bearish):
        return False

    # 현재 시가 >= 직전 종가  and  현재 종가 <= 직전 시가
    return curr.open >= prev.close and curr.close <= prev.open


# ------------------------------------------------------------------ #
#  손절/익절 계산 헬퍼                                                 #
# ------------------------------------------------------------------ #

def _long_stop(low_point: float) -> float:
    """Long 손절: 파동 최저점 2틱 아래"""
    tick = get_tick_size(low_point)
    return low_point - (tick * 2)


def _short_stop(high_point: float) -> float:
    """Short 손절: 파동 최고점 2틱 위"""
    tick = get_tick_size(high_point)
    return high_point + (tick * 2)


# ------------------------------------------------------------------ #
#  박스 이탈 + 패턴 → 진입 신호 감지                                  #
# ------------------------------------------------------------------ #

def detect_entry_signal(
    curr: Candle,
    prev: Optional[Candle],
    box: BoxRange,
) -> Optional[EntrySignal]:
    """
    5분봉 캔들 + 박스 범위로 진입 신호 탐지.

    규칙:
    - 박스 내부에서 발생한 패턴은 모두 무시 (휩소)
    - Long:  curr.low  < box.low  → 하방 이탈 확인 후 반전 패턴
    - Short: curr.high > box.high → 상방 이탈 확인 후 반전 패턴
    - 두 방향 동시 이탈(양봉이 박스를 완전히 관통) → 신호 없음
    """
    broke_down = curr.low  < box.low
    broke_up   = curr.high > box.high

    # 양방향 동시 돌파 → 불확실 신호 제거
    if broke_down and broke_up:
        logger.debug(f"[{curr.time}] 양방향 돌파 → 신호 무시")
        return None

    if broke_down:
        return _check_long_pattern(curr, prev, box)

    if broke_up:
        return _check_short_pattern(curr, prev, box)

    return None


def _check_long_pattern(
    curr: Candle,
    prev: Optional[Candle],
    box: BoxRange,
) -> Optional[EntrySignal]:
    """하방 이탈 후 Long 반전 패턴 검색 (망치형 우선, 이후 장악형)"""
    from config import STRATEGY
    
    # [유튜브 거래량 급감 필터] 하방 이탈/휩소 발생 시 투매(대량 거래)가 아닌지 확인
    # 수정: 반등하는 현재봉(curr)이 아니라, 박스를 깨고 내려가던 직전봉(prev)의 거래량이 씨가 말랐는지 검사
    if box.volume > 0 and prev is not None:
        avg_box_5m_vol = box.volume / 3.0
        # 직전 하락봉의 거래량이 허용치보다 많으면 진짜 하락(투매)일 수 있으므로 진입 포기
        if prev.volume > avg_box_5m_vol * STRATEGY.pullback_volume_ratio:
            return None

    # ── 망치형 ──
    if is_hammer(curr):
        trigger = curr.high               # 망치형 고점 돌파 시 진입
        stop    = _long_stop(curr.low)
        tp      = box.high
        logger.info(f"[{curr.time}] 망치형 Long 신호  진입:{trigger:,.0f}  손절:{stop:,.0f}  익절:{tp:,.0f}")
        return EntrySignal(
            direction=Direction.LONG,
            pattern=PatternType.HAMMER,
            entry_type=EntryType.TRIGGER,
            trigger_price=trigger,
            stop_loss=stop,
            take_profit=tp,
            candle_time=curr.time,
        )

    # ── 상승 장악형 ──
    if prev is not None and is_bullish_engulfing(curr, prev):
        # 장악형은 직전 캔들이 박스 하방에 있어야 유효
        if prev.low < box.low:
            trigger = curr.close
            stop    = _long_stop(min(curr.low, prev.low))
            tp      = box.high
            logger.info(f"[{curr.time}] 상승장악형 Long 신호  진입:{trigger:,.0f}  손절:{stop:,.0f}  익절:{tp:,.0f}")
            return EntrySignal(
                direction=Direction.LONG,
                pattern=PatternType.BULLISH_ENGULF,
                entry_type=EntryType.IMMEDIATE,
                trigger_price=trigger,
                stop_loss=stop,
                take_profit=tp,
                candle_time=curr.time,
            )

    return None


def _check_short_pattern(
    curr: Candle,
    prev: Optional[Candle],
    box: BoxRange,
) -> Optional[EntrySignal]:
    """상방 이탈 후 Short 반전 패턴 검색 (역망치형 우선, 이후 장악형)"""
    from config import STRATEGY

    # [유튜브 거래량 급감 필터] 휩소 발생 시 대량 거래가 실린 찐돌파가 아닌지 확인
    # 수정: 꺾이는 현재봉(curr)이 아니라, 박스를 뚫고 올라가던 직전봉(prev)의 거래량이 적었는지 검사
    if box.volume > 0 and prev is not None:
        avg_box_5m_vol = box.volume / 3.0
        if prev.volume > avg_box_5m_vol * STRATEGY.pullback_volume_ratio:
            return None

    # ── 역망치형 ──
    if is_shooting_star(curr):
        trigger = curr.low                # 역망치형 저점 하향 돌파 시 진입
        stop    = _short_stop(curr.high)
        tp      = box.low
        logger.info(f"[{curr.time}] 역망치형 Short 신호  진입:{trigger:,.0f}  손절:{stop:,.0f}  익절:{tp:,.0f}")
        return EntrySignal(
            direction=Direction.SHORT,
            pattern=PatternType.SHOOTING_STAR,
            entry_type=EntryType.TRIGGER,
            trigger_price=trigger,
            stop_loss=stop,
            take_profit=tp,
            candle_time=curr.time,
        )

    # ── 하락 장악형 ──
    if prev is not None and is_bearish_engulfing(curr, prev):
        if prev.high > box.high:
            trigger = curr.close
            stop    = _short_stop(max(curr.high, prev.high))
            tp      = box.low
            logger.info(f"[{curr.time}] 하락장악형 Short 신호  진입:{trigger:,.0f}  손절:{stop:,.0f}  익절:{tp:,.0f}")
            return EntrySignal(
                direction=Direction.SHORT,
                pattern=PatternType.BEARISH_ENGULF,
                entry_type=EntryType.IMMEDIATE,
                trigger_price=trigger,
                stop_loss=stop,
                take_profit=tp,
                candle_time=curr.time,
            )

    return None


# ------------------------------------------------------------------ #
#  전략 B: 거래량 동반 순추세 돌파 (Breakout)                           #
# ------------------------------------------------------------------ #
def detect_strategy_B(
    curr: Candle,
    prev: Optional[Candle],
    box: BoxRange,
) -> Optional[EntrySignal]:
    """
    박스 상단을 강하게 돌파하는 순방향 추세 로직.
    - Long: 종가가 박스 상단을 돌파 (시가는 박스 안 또는 경계선)
    - 손절선: 박스 상단 0.1% 아래 (이전 저항선이자 이제는 지지선)
    - 손익비: 3.0 목표
    """
    if curr.close > box.high and curr.open <= box.high:
        trigger = curr.close
        # 핵심 수정: 손절을 박스 상단 바로 아래로 (음슡 0.1%)
        # 이전 백테스트의 스탱 할퍼 에러: 박스 중간점 → 박스 상단 0.1% 아래로 수정
        stop = _long_stop(box.high)  # box.high 의 0.1% 아래
        tp = trigger + (trigger - stop) * 3.0  # 손익비 3.0
        return EntrySignal(
            direction=Direction.LONG,
            pattern=PatternType.BREAKOUT,
            entry_type=EntryType.IMMEDIATE,
            trigger_price=trigger,
            stop_loss=stop,
            take_profit=tp,
            candle_time=curr.time,
        )
    return None


# ------------------------------------------------------------------ #
#  전략 C: 돌파 후 눌림목 지지 (Pullback)                                #
# ------------------------------------------------------------------ #
def detect_strategy_C(
    candles: list[Candle], # 09:15 이후의 5분봉 전체
    box: BoxRange,
) -> Optional[EntrySignal]:
    """
    박스 상단 돌파 이후, 다시 박스 상단 근처로 조정받을 때 지지 확인 후 진입.
    조건: 직전 캔들이 돌파한 이력 있고, 현재봉 저가가 박스 상단 ±1.0% 이내,
          종가는 박스 상단 위를 지켜낸 경우 (이전 저항 → 지지 전환 확인)
    """
    if len(candles) < 3:
        return None
        
    curr = candles[-1]
    
    # 이전에 돌파한 적이 있는지 확인
    breakout_occurred = any(c.close > box.high for c in candles[:-1])
    
    if breakout_occurred:
        # 수정: 허용 오차를 ±0.2% → ±1.0%로 완화 (현실적 눌림목 범위)
        # 저가가 box.high -1.0% ~ +0.5% 사이로 내려왔으나 종가는 지지
        lower_bound = box.high * (1 - 0.010)  # 1.0% 아래까지 허용
        upper_bound = box.high * (1 + 0.005)  # 0.5% 위까지 허용
        if lower_bound <= curr.low <= upper_bound and curr.close > box.high:
            from config import STRATEGY
            
            # [유튜브 거래량 급감 필터] 눌림목 하락 시 거래량이 씨가 말랐는지 확인
            if box.volume > 0:
                avg_box_5m_vol = box.volume / 3.0
                if curr.volume > avg_box_5m_vol * STRATEGY.pullback_volume_ratio:
                    return None
                    
            trigger = curr.close
            stop = _long_stop(box.high * 0.995) # 박스 상단 0.5% 아래
            tp = trigger + (trigger - stop) * 3.0 # 손익비 3배
            return EntrySignal(
                direction=Direction.LONG,
                pattern=PatternType.PULLBACK,
                entry_type=EntryType.IMMEDIATE,
                trigger_price=trigger,
                stop_loss=stop,
                take_profit=tp,
                candle_time=curr.time,
            )
            
    return None

def detect_strategy_D(one_min_candles: list[Candle]) -> EntrySignal | None:
    """
    전략 D (유튜브 김사부2 시가 회복 기법):
    - 첫 1분봉 시가(오늘의 시가)를 기준으로 함.
    - 장 시작 후 주가가 한 번이라도 시가 아래로 이탈(음봉 혹은 꼬리)했어야 함.
    - 현재 1분봉이 시가를 다시 위로 돌파(Cross-Up)하는 순간 매수.
    - 손절선(Stop Loss): 당일 형성된 최저가.
    """
    if len(one_min_candles) < 2:
        return None
        
    opening_price = one_min_candles[0].open
    
    # 1. 시가 아래로 내려간 적이 있는지 확인 & 당일 최저가 탐색
    lowest_price = min(c.low for c in one_min_candles)
    has_dipped = lowest_price < opening_price
    if not has_dipped:
        return None
        
    curr = one_min_candles[-1]
    prev = one_min_candles[-2]
    
    # 2. 직전 캔들의 종가는 시가 이하였고, 현재 캔들의 종가가 시가를 강하게 돌파했는지 확인
    # (돌파하는 순간을 포착하기 위해 prev.close <= open < curr.close)
    if prev.close <= opening_price and curr.close > opening_price:
        # 매수 타점 포착
        entry_price = curr.close
        stop_loss = lowest_price
        
        # 만약 손절폭이 너무 크면(예: 5% 이상) 리스크 관리상 거부
        if stop_loss > 0 and (entry_price - stop_loss) / entry_price > 0.05:
            return None
            
        return EntrySignal(
            direction=Direction.LONG,
            pattern="D (Opening Recovery)",
            entry_type=EntryType.IMMEDIATE,
            trigger_price=entry_price,
            stop_loss=stop_loss,
            take_profit=entry_price * 1.05,  # 기본 TP는 PositionManager에서 RR 기반으로 재조정됨
            candle_time=curr.time
        )
        
    return None
