"""분봉 원본 데이터 확인"""
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_kis_config
from market.api_client import KISClient
from market.data_processor import parse_minute_candles, get_first_15m_candle

cfg    = load_kis_config()
client = KISClient(cfg)

# 조회 시각 "091500" 로 요청
raw = client.get_minute_ohlcv("005930", "091500")
print(f"raw 건수: {len(raw)}")
for r in raw[:5]:
    print(" ", r.get("stck_bsop_date"), r.get("stck_cntg_hour"),
          "O:", r.get("stck_oprc"), "H:", r.get("stck_hgpr"),
          "L:", r.get("stck_lwpr"), "C:", r.get("stck_prpr"))

print()
# parse 결과
candles = parse_minute_candles(raw)
print(f"parse 건수: {len(candles)}")
for c in candles[:5]:
    print(" ", c.time, "O:", c.open, "H:", c.high, "L:", c.low, "C:", c.close)

# 오전 시간대 필터
morning = [c for c in candles if "090000" <= c.time < "091500"]
print(f"\n09:00~09:14 캔들: {len(morning)}개")
for c in morning:
    print(" ", c.time, c.open, c.high, c.low, c.close)

first = get_first_15m_candle(candles)
print(f"\n첫15분봉: {first}")
