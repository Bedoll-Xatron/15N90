import logging
from pykrx import stock as krx
from market.holidays import get_calendar
import pandas as pd
from datetime import timedelta

logging.basicConfig(level=logging.INFO)

cal = get_calendar()
today = cal.last_trading_day()

# Find yesterday (previous trading day)
yesterday = today - timedelta(days=1)
while not cal.is_trading_day(yesterday):
    yesterday -= timedelta(days=1)

yesterday_str = yesterday.strftime("%Y%m%d")
print("Using date:", yesterday_str)

try:
    df_kq = krx.get_market_cap(yesterday_str, market="KOSDAQ")
    print(df_kq.head())
except Exception as e:
    print(f"Error: {e}")
