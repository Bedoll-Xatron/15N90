import os, requests, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

key    = os.getenv("KIS_APP_KEY", "")
secret = os.getenv("KIS_APP_SECRET", "")
url    = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")

print(f"URL: {url}")
print(f"KEY: {key[:8]}...")

# 1) 토큰 발급
r = requests.post(f"{url}/oauth2/tokenP",
    json={"grant_type": "client_credentials", "appkey": key, "appsecret": secret},
    timeout=10)
r.raise_for_status()
token = r.json()["access_token"]
print("토큰 발급 성공")

headers = {
    "authorization": f"Bearer {token}",
    "appkey": key, "appsecret": secret,
    "tr_id": "FHKST03010200", "custtype": "P",
}

def fetch(params):
    r = requests.get(
        f"{url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        headers=headers, params=params, timeout=10)
    d = r.json()
    rows = d.get("output2", [])
    msg  = d.get("msg1", "")[:60]
    return rows, d.get("rt_cd"), msg

# 2) 오늘 분봉
base_params = {
    "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
    "FID_INPUT_ISCD": "005930", "FID_INPUT_HOUR_1": "103000",
    "FID_PW_DATA_INCU_YN": "N",
}
rows, rc, msg = fetch(base_params)
print(f"\n[오늘 분봉] {len(rows)}건  rt_cd={rc}  msg={msg}")
if rows:
    print("  샘플:", rows[0])

# 3) 과거 날짜 파라미터 테스트
hist_params = dict(base_params)
hist_params["FID_INPUT_DATE_1"] = "20240103"
rows3, rc3, msg3 = fetch(hist_params)
print(f"\n[과거분봉 20240103] {len(rows3)}건  rt_cd={rc3}  msg={msg3}")
if rows3:
    print("  샘플:", rows3[0])
    print("  => 과거 분봉 지원 확인!")
else:
    print("  => 과거 분봉 미지원 (당일만 제공)")
