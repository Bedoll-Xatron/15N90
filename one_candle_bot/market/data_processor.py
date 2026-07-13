"""
2단계: 데이터 처리 모듈

- ATR(14) 계산
- 분봉 → 15분봉 집계
- 15분봉 박스 범위 확정
- 일평균 거래량 계산
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoxRange:
    high: float
    low: float
    volume: int = 0

    @property
    def size(self) -> float:
        return self.high - self.low

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2


@dataclass(frozen=True)
class Candle:
    time: str   # HHMMSS
    open: float
    high: float
    low: float
    close: float
    volume: int


# ------------------------------------------------------------------ #
#  ATR 계산                                                           #
# ------------------------------------------------------------------ #

def calc_atr(daily_ohlcv: list[dict], period: int = 14) -> float:
    """
    일봉 데이터로 ATR(period일) 계산 (단순이동평균 방식)

    daily_ohlcv: KIS get_daily_ohlcv() 반환값 (최신순 정렬)
      필드: stck_hgpr(고가), stck_lwpr(저가), stck_clpr(종가)
    """
    needed = period + 1
    if len(daily_ohlcv) < needed:
        raise ValueError(
            f"ATR 계산에 최소 {needed}일치 데이터 필요 (현재 {len(daily_ohlcv)}일)"
        )

    rows = daily_ohlcv[:needed]
    tr_list: list[float] = []

    for i in range(period):
        high       = float(rows[i]["stck_hgpr"])
        low        = float(rows[i]["stck_lwpr"])
        prev_close = float(rows[i + 1]["stck_clpr"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    atr = sum(tr_list) / period
    logger.debug(f"ATR({period}) = {atr:,.0f}원  (TR 범위: {min(tr_list):,.0f} ~ {max(tr_list):,.0f})")
    return atr


# ------------------------------------------------------------------ #
#  분봉 데이터 처리                                                   #
# ------------------------------------------------------------------ #

def parse_minute_candles(raw: list[dict]) -> list[Candle]:
    """
    KIS get_minute_ohlcv() 응답 → Candle 리스트 변환 (오래된 순 정렬)

    KIS 분봉 필드:
      stck_bsop_date: 날짜(YYYYMMDD), stck_cntg_hour: 시각(HHMMSS)
      stck_oprc: 시가, stck_hgpr: 고가, stck_lwpr: 저가
      stck_prpr: 현재가(=종가), stck_clpr: 종가 (일부 응답만 존재)
      cntg_vol: 거래량
    """
    candles: list[Candle] = []
    for row in reversed(raw):  # KIS는 최신순 → 오래된 순으로 뒤집기
        try:
            # stck_prpr(현재가) 우선, 없으면 stck_clpr(종가) 사용
            close_val = row.get("stck_prpr") or row.get("stck_clpr")
            if not close_val:
                continue
            candles.append(Candle(
                time=row.get("stck_cntg_hour", ""),
                open=float(row["stck_oprc"]),
                high=float(row["stck_hgpr"]),
                low=float(row["stck_lwpr"]),
                close=float(close_val),
                volume=int(row.get("cntg_vol", 0)),
            ))
        except (KeyError, ValueError):
            continue
    return candles


def aggregate_to_15m(minute_candles: list[Candle], base_minute: int = 0) -> list[Candle]:
    """
    1분봉 리스트 → 15분봉 집계
    base_minute: 집계 시작 기준 분 (0이면 00, 15, 30, 45분 단위)
    """
    if not minute_candles:
        return []

    buckets: dict[str, list[Candle]] = {}

    for c in minute_candles:
        if len(c.time) < 4:
            continue
        hh = int(c.time[:2])
        mm = int(c.time[2:4])
        slot_mm = (mm // 15) * 15
        key = f"{hh:02d}{slot_mm:02d}00"
        buckets.setdefault(key, []).append(c)

    result: list[Candle] = []
    for key in sorted(buckets):
        group = buckets[key]
        result.append(Candle(
            time=key,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
        ))

    return result


def get_first_15m_candle(minute_candles: list[Candle]) -> Optional[Candle]:
    """
    09:00 ~ 09:15 구간의 15분봉 반환
    minute_candles: 오래된 순 정렬된 1분봉 리스트
    """
    group = [c for c in minute_candles if "090000" <= c.time < "091500"]
    if not group:
        return None
    return Candle(
        time="090000",
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum(c.volume for c in group),
    )


def aggregate_candles(candles: list[Candle], interval_min: int) -> list[Candle]:
    """
    1분봉 리스트를 interval_min 분봉으로 집계.
    aggregate_to_15m 의 일반화 버전.
    """
    if not candles or interval_min <= 0:
        return []

    buckets: dict[str, list[Candle]] = {}
    for c in candles:
        if len(c.time) < 4:
            continue
        hh = int(c.time[:2])
        mm = int(c.time[2:4])
        slot_mm = (mm // interval_min) * interval_min
        key = f"{hh:02d}{slot_mm:02d}00"
        buckets.setdefault(key, []).append(c)

    result: list[Candle] = []
    for key in sorted(buckets):
        group = buckets[key]
        result.append(Candle(
            time=key,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
        ))
    return result


def candle_to_box(candle: Candle) -> BoxRange:
    """Candle → BoxRange 변환"""
    return BoxRange(high=candle.high, low=candle.low, volume=candle.volume)


# ------------------------------------------------------------------ #
#  거래량 통계                                                         #
# ------------------------------------------------------------------ #

def calc_avg_daily_volume(daily_ohlcv: list[dict], period: int = 20) -> float:
    """
    최근 period일 일평균 거래량 계산
    필드: acml_vol (누적거래량) 또는 stck_vol
    """
    vols: list[int] = []
    for row in daily_ohlcv[:period]:
        raw = row.get("acml_vol") or row.get("stck_vol", "0")
        try:
            vols.append(int(str(raw).replace(",", "")))
        except ValueError:
            continue

    if not vols:
        return 0.0

    avg = sum(vols) / len(vols)
    logger.debug(f"일평균 거래량({period}일): {avg:,.0f}주")
    return avg
