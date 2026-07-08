"""
분봉 CSV 로더

backtest/data/{ticker}/{ticker}_{YYYYMMDD}.csv 를 읽어
Candle 리스트로 반환.
"""
import csv
import logging
from pathlib import Path

from market.data_processor import Candle

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


def load_minute_candles(ticker: str, yyyymmdd: str) -> list[Candle]:
    """
    CSV 파일 → 오래된 순 Candle 리스트 반환.
    파일 없으면 빈 리스트.

    Parameters
    ----------
    ticker    : 종목코드 (예: "005930")
    yyyymmdd  : 날짜 (예: "20240103")
    """
    path = DATA_DIR / ticker / f"{ticker}_{yyyymmdd}.csv"
    if not path.exists():
        return []

    candles: list[Candle] = []
    try:
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = str(row.get("time", "")).strip().zfill(6)
                if t < "090000":  # 프리마켓 제외
                    continue
                try:
                    candles.append(Candle(
                        time=t,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                    ))
                except (KeyError, ValueError):
                    continue
    except Exception as e:
        logger.warning(f"CSV 읽기 실패 [{path}]: {e}")
        return []

    # 시간 오름차순 정렬 보장
    candles.sort(key=lambda c: c.time)
    return candles


def available_dates(ticker: str) -> list[str]:
    """다운로드된 날짜 목록 반환 (YYYYMMDD, 오름차순)"""
    d = DATA_DIR / ticker
    if not d.exists():
        return []
    return sorted(
        f.stem.split("_")[1]
        for f in d.glob(f"{ticker}_????????.csv")
        if len(f.stem.split("_")) == 2
    )
