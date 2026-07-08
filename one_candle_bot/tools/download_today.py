"""오늘 전 구간 분봉 수집 (09:00 ~ 현재)"""
import csv, json, os, sys, time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from backtest.minute_loader import DATA_DIR

KEY    = os.getenv("KIS_APP_KEY", "")
SECRET = os.getenv("KIS_APP_SECRET", "")
URL    = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
TODAY  = date.today().strftime("%Y%m%d")

TICKERS = {"005930": "삼성전자", "000660": "SK하이닉스", "068270": "셀트리온"}
# 30건씩 반환 → 09:00~15:30 커버 위해 6구간 호출
TIMES = ["153000", "143000", "133000", "120000", "110000", "093000"]


def get_token():
    r = requests.post(f"{URL}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": KEY, "appsecret": SECRET},
        timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch(token, ticker, until):
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": KEY, "appsecret": SECRET,
        "tr_id": "FHKST03010200", "custtype": "P",
    }
    params = {
        "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker, "FID_INPUT_HOUR_1": until,
        "FID_PW_DATA_INCU_YN": "N",
    }
    r = requests.get(
        f"{URL}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        headers=headers, params=params, timeout=10)
    data = r.json()
    if data.get("rt_cd") != "0":
        raise RuntimeError(data.get("msg1", "API 오류"))
    return data.get("output2", [])


def download_ticker(token, ticker):
    seen = {}
    for until in TIMES:
        try:
            rows = fetch(token, ticker, until)
        except Exception as e:
            print(f"  [{ticker}] {until} 조회 실패: {e}")
            continue

        for r in rows:
            t = r.get("stck_cntg_hour", "")
            if t < "090000":
                continue
            seen[t] = (
                t,
                int(r.get("stck_oprc", 0)),
                int(r.get("stck_hgpr", 0)),
                int(r.get("stck_lwpr", 0)),
                int(r.get("stck_prpr",  r.get("stck_clpr", 0))),
                int(r.get("cntg_vol",  0)),
            )
        time.sleep(0.25)

    return sorted(seen.values(), key=lambda x: x[0])


def save(ticker, rows):
    out_dir = DATA_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}_{TODAY}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    return path, len(rows)


def main():
    print(f"오늘({TODAY}) 실제 분봉 수집 시작")
    token = get_token()
    print("토큰 발급 완료\n")

    for ticker, name in TICKERS.items():
        print(f"[{name}({ticker})] 수집 중...")
        rows = download_ticker(token, ticker)
        if not rows:
            print(f"  데이터 없음 (장 마감 또는 휴장일)\n")
            continue
        path, n = save(ticker, rows)
        print(f"  {n}건 저장 → {path}")
        if rows:
            print(f"  구간: {rows[0][0]} ~ {rows[-1][0]}\n")


if __name__ == "__main__":
    main()
