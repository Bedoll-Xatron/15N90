"""
yfinance 기반 분봉 다운로더

무료, API 키 불필요, 최근 60일 1분봉 지원.
한국 종목은 종목코드 뒤에 .KS (KOSPI) 또는 .KQ (KOSDAQ) 붙임.

사용법:
  python tools/download_yfinance.py
"""
import csv
import logging
import sys
import time
from pathlib import Path

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.minute_loader import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# KOSPI 종목은 .KS, KOSDAQ은 .KQ
TICKERS = {
    "005930": ("005930.KS", "삼성전자"),
    "000660": ("000660.KS", "SK하이닉스"),
    "068270": ("068270.KS", "셀트리온"),
}


def download_and_save(ticker_kr: str, ticker_yf: str, name: str) -> int:
    logger.info(f"[{name}({ticker_kr})] 다운로드 중... ({ticker_yf})")

    try:
        df = yf.download(
            ticker_yf,
            period="60d",
            interval="5m",   # 1m은 8일 제한 → 5m은 60일 제공
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        logger.error(f"  다운로드 실패: {e}")
        return 0

    if df.empty:
        logger.warning(f"  데이터 없음")
        return 0

    # yfinance 컬럼: Open, High, Low, Close, Volume (MultiIndex일 수 있음)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })

    # 한국 시간 (UTC+9) 변환
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert("Asia/Seoul")
    else:
        df.index = df.index.tz_convert("Asia/Seoul")

    # 날짜별로 분리하여 저장
    saved = 0
    for date_key, group in df.groupby(df.index.date):
        yyyymmdd = date_key.strftime("%Y%m%d")

        # 장 시간(09:00~15:30) 필터
        group = group.between_time("09:00", "15:30")
        if group.empty:
            continue

        out_dir = DATA_DIR / ticker_kr
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ticker_kr}_{yyyymmdd}.csv"

        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            for ts, row in group.iterrows():
                t = ts.strftime("%H%M%S")
                w.writerow([
                    t,
                    int(row["open"]),
                    int(row["high"]),
                    int(row["low"]),
                    int(row["close"]),
                    int(row["volume"]),
                ])
        saved += 1

    logger.info(f"  {saved}일치 저장 완료 → backtest/data/{ticker_kr}/")
    return saved


def main() -> None:
    logger.info("yfinance 분봉 다운로드 시작 (최근 60일)")

    total = 0
    for ticker_kr, (ticker_yf, name) in TICKERS.items():
        n = download_and_save(ticker_kr, ticker_yf, name)
        total += n
        time.sleep(1)

    logger.info(f"\n완료: 총 {total}일치 분봉 CSV 저장")


if __name__ == "__main__":
    main()
