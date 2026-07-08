"""
KIS OpenAPI 분봉 다운로더

주의: KIS API는 당일 분봉 조회만 공식 지원합니다.
      이력 분봉 수집은 tools/convert_hts_csv.py + HTS 수동 내보내기를 사용하세요.

사용법:
  # 오늘 분봉 저장
  python tools/download_minute_csv.py --ticker 005930

  # 여러 종목
  python tools/download_minute_csv.py --ticker 005930 000660 068270
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

DATA_DIR     = Path(__file__).parent.parent / "backtest" / "data"
TOKEN_CACHE  = Path(__file__).parent.parent / ".token_cache.json"
REQUEST_TIMEOUT = 10


# ------------------------------------------------------------------ #
#  KIS 인증                                                           #
# ------------------------------------------------------------------ #

def _get_token(base_url: str, app_key: str, app_secret: str) -> str:
    if TOKEN_CACHE.exists():
        try:
            d = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            from datetime import datetime
            if datetime.now().isoformat() < d["expires_at"]:
                return d["access_token"]
        except Exception:
            pass

    resp = requests.post(
        f"{base_url}/oauth2/tokenP",
        json={"grant_type": "client_credentials",
              "appkey": app_key, "appsecret": app_secret},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": data["access_token"],
        "expires_at": data.get("access_token_token_expired", ""),
    }), encoding="utf-8")
    return data["access_token"]


def _headers(base_url, app_key, app_secret, tr_id):
    token = _get_token(base_url, app_key, app_secret)
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }


# ------------------------------------------------------------------ #
#  분봉 조회 (당일)                                                    #
# ------------------------------------------------------------------ #

def fetch_minute_candles(
    base_url: str, app_key: str, app_secret: str,
    ticker: str,
    until_time: str = "153000",
) -> list[dict]:
    """
    KIS 당일 1분봉 조회.
    until_time: HHMMSS — 이 시각 이전 데이터 반환 (최대 30건)
    """
    resp = requests.get(
        f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        headers=_headers(base_url, app_key, app_secret, "FHKST03010200"),
        params={
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_HOUR_1": until_time,
            "FID_PW_DATA_INCU_YN": "N",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("rt_cd") != "0":
        raise RuntimeError(f"API 오류: {data.get('msg1')}")
    return data.get("output2", [])


def download_today(
    base_url: str, app_key: str, app_secret: str,
    ticker: str,
) -> list[tuple]:
    """당일 09:00~15:30 분봉 수집 (3회 호출로 전체 커버)"""
    all_rows: dict[str, tuple] = {}

    for until in ("153000", "122000", "090100"):
        try:
            raw = fetch_minute_candles(base_url, app_key, app_secret, ticker, until)
        except Exception as e:
            logger.warning(f"  조회 실패 (until={until}): {e}")
            continue

        for r in raw:
            t = r.get("stck_cntg_hour", "")
            if not t or t < "090000":
                continue
            all_rows[t] = (
                t,
                int(r.get("stck_oprc", 0)),
                int(r.get("stck_hgpr", 0)),
                int(r.get("stck_lwpr", 0)),
                int(r.get("stck_clpr", 0)),
                int(r.get("cntg_vol", 0)),
            )
        time.sleep(0.2)

    return sorted(all_rows.values(), key=lambda x: x[0])


# ------------------------------------------------------------------ #
#  CSV 저장                                                            #
# ------------------------------------------------------------------ #

def save_csv(ticker: str, trade_date: str, rows: list[tuple]) -> Path:
    """
    rows: [(time, open, high, low, close, volume), ...]
    저장: backtest/data/{ticker}/{ticker}_{YYYYMMDD}.csv
    """
    out_dir = DATA_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ticker}_{trade_date}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)

    logger.info(f"  저장: {out_path}  ({len(rows)}행)")
    return out_path


# ------------------------------------------------------------------ #
#  진입점                                                              #
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="KIS 당일 분봉 CSV 다운로더")
    parser.add_argument("--ticker", nargs="+", required=True, help="종목코드 (예: 005930 000660)")
    args = parser.parse_args()

    app_key    = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    base_url   = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")

    if not app_key or app_key.startswith("여기에"):
        print(
            "\n[오류] .env 에 KIS_APP_KEY 가 설정되지 않았습니다.\n"
            "  1) 발급: https://apiportal.koreainvestment.com\n"
            "  2) 프로젝트 루트 .env 파일에 입력 후 재실행\n"
            "\n이력 분봉은 tools/convert_hts_csv.py + HTS 수동 내보내기를 사용하세요.\n"
            "  자세한 방법: backtest/data/README.md\n"
        )
        sys.exit(1)

    today = date.today().strftime("%Y%m%d")
    logger.info(f"다운로드 대상: {args.ticker}  날짜: {today}")

    for ticker in args.ticker:
        logger.info(f"[{ticker}] 조회 중...")
        rows = download_today(base_url, app_key, app_secret, ticker)
        if not rows:
            logger.warning(f"[{ticker}] 데이터 없음 (장 마감 후 또는 비영업일)")
            continue
        save_csv(ticker, today, rows)

    print("\n완료. 이력 분봉은 HTS에서 내보낸 후 convert_hts_csv.py 로 변환하세요.")


if __name__ == "__main__":
    main()
