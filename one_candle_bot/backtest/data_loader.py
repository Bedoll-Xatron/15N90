"""
pykrx 기반 일봉 데이터 로더

실제 분봉 데이터 없이 일봉으로 전략을 근사 검증하는 용도.
네트워크 부하 줄이기 위해 결과를 .cache/ 에 피클로 저장.
"""
import logging
import pickle
from pathlib import Path

import pandas as pd
from pykrx import stock as krx

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)

# 시장 방향 대리 ETF (pykrx index API 버그로 ETF 사용)
KOSPI_PROXY  = "069500"   # KODEX 200
KOSDAQ_PROXY = "229200"   # KODEX KOSDAQ150


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.pkl"


def _load_cache(key: str) -> pd.DataFrame | None:
    p = _cache_path(key)
    if p.exists():
        return pickle.loads(p.read_bytes())
    return None


def _save_cache(key: str, df: pd.DataFrame) -> None:
    _cache_path(key).write_bytes(pickle.dumps(df))


def load_stock_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    종목 일봉 OHLCV 반환 (최신순 정렬, 캐시 사용)

    Returns
    -------
    columns: open, high, low, close, volume, change_pct
    index  : DatetimeIndex (날짜 오름차순)
    """
    key = f"{ticker}_{start}_{end}"
    cached = _load_cache(key)
    if cached is not None:
        return cached

    logger.info(f"pykrx 다운로드: {ticker} {start}~{end}")
    raw = krx.get_market_ohlcv_by_date(start, end, ticker)
    if raw.empty:
        return pd.DataFrame()

    df = raw.rename(columns={
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume", "등락률": "change_pct",
    })[["open", "high", "low", "close", "volume", "change_pct"]]
    df.index.name = "date"

    _save_cache(key, df)
    return df


def load_market_proxy(start: str, end: str) -> pd.DataFrame:
    """
    시장 방향 지표 반환

    Returns
    -------
    columns: kospi_chg, kosdaq_chg  (전일 대비 등락률 %)
    index  : DatetimeIndex
    """
    key = f"market_{start}_{end}"
    cached = _load_cache(key)
    if cached is not None:
        return cached

    logger.info(f"pykrx 시장 프록시 다운로드 {start}~{end}")
    k200  = load_stock_ohlcv(KOSPI_PROXY,  start, end)
    kq150 = load_stock_ohlcv(KOSDAQ_PROXY, start, end)
    
    if not k200.empty:
        k200["ema21"] = k200["close"].ewm(span=21, adjust=False).mean()

    df = pd.DataFrame({
        "kospi_chg":  k200["change_pct"]  if not k200.empty  else 0.0,
        "kosdaq_chg": kq150["change_pct"] if not kq150.empty else 0.0,
        "kospi_close": k200["close"] if not k200.empty else 0.0,
        "kospi_ema21": k200["ema21"] if not k200.empty else 0.0,
    }).fillna(0.0)

    _save_cache(key, df)
    return df
