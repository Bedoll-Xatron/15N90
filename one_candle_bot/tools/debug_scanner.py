"""스캐너 내부 진단"""
import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_kis_config
from market.api_client import KISClient
from market.data_processor import (
    parse_minute_candles, get_first_15m_candle,
    calc_atr, calc_avg_daily_volume, aggregate_candles,
)
from backtest.data_loader import load_stock_ohlcv
from backtest.engine import _daily_to_atr_rows, _daily_to_vol_rows, BacktestParams, _detect_signal_with_params
from strategy.filters import check_atr_filter, check_volume_filter, check_market_direction
from market.data_processor import candle_to_box

cfg    = load_kis_config()
client = KISClient(cfg)
today  = date.today().strftime("%Y%m%d")
params = BacktestParams()

print(f"날짜: {today}\n")

for ticker, name in [("005930","삼성전자"),("000660","SK하이닉스"),("068270","셀트리온")]:
    print(f"{'='*50}")
    print(f"  {name} ({ticker})")
    print(f"{'='*50}")

    # 일봉 로드
    ohlcv = load_stock_ohlcv(ticker, "20230101", today)
    n = len(ohlcv)
    print(f"  일봉: {n}행  최신: {ohlcv.index[-1].date()}")

    atr_rows = _daily_to_atr_rows(ohlcv.iloc[n-params.atr_period-1:n])
    atr = calc_atr(atr_rows, params.atr_period)
    vol_rows = _daily_to_vol_rows(ohlcv.iloc[max(0,n-21):n])
    avg_vol  = calc_avg_daily_volume(vol_rows, 20)
    print(f"  ATR(14): {atr:,.0f}원   일평균거래량: {avg_vol:,.0f}주")

    # 첫 15분봉
    raw    = client.get_minute_ohlcv(ticker, "091500")
    cands  = parse_minute_candles(raw)
    f15    = get_first_15m_candle(cands)
    if f15 is None:
        print("  첫 15분봉 없음\n"); continue

    box = candle_to_box(f15)
    atr_r = check_atr_filter(box.size, atr, params.atr_ratio)
    vol_r = check_volume_filter(f15.volume, avg_vol/26, params.vol_mult)
    print(f"  박스 크기: {box.size:,.0f}원  ATR비율: {box.size/atr:.1%}")
    print(f"  ATR 필터: {'통과' if atr_r.passed else '탈락'}  거래량 필터: {'통과' if vol_r.passed else '탈락'}")

    if not (atr_r.passed and vol_r.passed):
        print(); continue

    # 5분봉 패턴 스캔
    raw2   = client.get_minute_ohlcv(ticker, "103000")
    cands2 = parse_minute_candles(raw2)
    monitoring = [c for c in cands2 if "091500" <= c.time <= "103000"]
    five_m = aggregate_candles(monitoring, 5)
    print(f"  5분봉(09:15~10:30): {len(five_m)}개")

    found = False
    for j in range(1, len(five_m)):
        sig = _detect_signal_with_params(five_m[j], five_m[j-1], box, params)
        if sig:
            print(f"  ★ {sig.direction.value} {sig.pattern.value}  진입:{sig.trigger_price:,}  손절:{sig.stop_loss:,}  익절:{sig.take_profit:,}")
            found = True
    if not found:
        print("  패턴 없음")
    print()
