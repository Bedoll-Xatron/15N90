import logging
from config import UNIVERSE
from backtest.data_loader import load_stock_ohlcv
from market.holidays import get_calendar
from market.universe import MAJOR_TICKERS

logging.basicConfig(level=logging.INFO)

today_str = get_calendar().last_trading_day().strftime("%Y%m%d")
start_str = "20230101"

stats = {
    "total": len(MAJOR_TICKERS),
    "data_fail": 0,
    "ema21_falling": 0,
    "below_ema21": 0,
    "below_ma5": 0,
    "vol_fail": 0,
    "liq_fail": 0,
    "passed": 0
}

for code, name in MAJOR_TICKERS.items():
    try:
        df = load_stock_ohlcv(code, start_str, today_str)
        if df.empty or len(df) < 22:
            stats["data_fail"] += 1
            continue

        df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
        recent_df = df.tail(21)
        
        current_close = float(recent_df["close"].iloc[-1])
        ema21_current = float(recent_df["ema21"].iloc[-1])
        ema21_prev = float(recent_df["ema21"].iloc[-2])
        
        # if ema21_current <= ema21_prev:
        #     stats["ema21_falling"] += 1
        #     continue
            
        # if current_close < ema21_current:
        #     stats["below_ema21"] += 1
        #     continue
            
        ma5 = recent_df["close"].tail(5).mean()
        # if current_close < ma5:
        #     stats["below_ma5"] += 1
        #     continue
        
        last = recent_df.iloc[-1]
        vol = float(last.get("volume", 0))
        trade_amt_est = vol * current_close
        
        is_mega_volume = trade_amt_est >= UNIVERSE.min_avg_trade_amount
        prev_19_days_vol = recent_df["volume"].iloc[:-1].mean()
        last_vol = float(recent_df["volume"].iloc[-1])
        is_volume_spike = (prev_19_days_vol > 0) and (last_vol >= prev_19_days_vol * 2.0)
        
        if not (is_mega_volume or is_volume_spike):
            stats["vol_fail"] += 1
            continue
            
        if trade_amt_est < 10_000_000_000:
            stats["liq_fail"] += 1
            continue
            
        stats["passed"] += 1

    except Exception as e:
        print(f"Error {code}: {e}")

print(f"Stats (no trend): {stats}")
