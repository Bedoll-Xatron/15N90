"""
분봉 합성 데이터 생성기

pykrx 일봉(open/high/low/close/volume)을 기반으로
현실적인 1분봉 데이터를 생성하여 backtest/data/ 에 저장합니다.

⚠ 합성 데이터 주의사항
  실제 분봉 패턴이 아니라 통계적 근사입니다.
  전략 로직 검증(코드 테스트) 용도로 사용하고,
  실전 의사결정은 반드시 실제 분봉으로 재검증하세요.

사용법:
  python tools/generate_minute_csv.py
  python tools/generate_minute_csv.py --tickers 005930 000660 --start 20240101 --end 20241231
"""
import argparse
import csv
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.data_loader import load_stock_ohlcv
from backtest.minute_loader import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

PATTERN_RATE  = 0.18   # 패턴 주입 비율 (18%)
SESSION_START = 9 * 60  # 09:00 (분 단위)
SESSION_END   = 15 * 60 + 30  # 15:30
N_MINUTES     = SESSION_END - SESSION_START  # 390분


# ================================================================== #
#  가격 경로 생성                                                      #
# ================================================================== #

def _price_path(n, open_p, close_p, high_p, low_p, rng):
    """
    Brownian bridge + 일봉 OHLC 제약 경로 생성.
    반환: n+1 개의 가격 포인트 (각 분봉의 경계값)
    """
    # 고가/저가 발생 위치 (이른 아침 or 오후에 편중)
    if close_p >= open_p:  # 상승일: 저가 먼저, 고가 나중
        low_t  = int(rng.integers(5,  n // 3))
        high_t = int(rng.integers(n // 2, n - 5))
    else:                   # 하락일: 고가 먼저, 저가 나중
        high_t = int(rng.integers(5,  n // 3))
        low_t  = int(rng.integers(n // 2, n - 5))

    # 핵심 웨이포인트 (시간, 가격) 정렬
    waypoints = sorted([
        (0,     open_p),
        (high_t, high_p),
        (low_t,  low_p),
        (n,      close_p),
    ])
    times  = [p[0] for p in waypoints]
    prices = [p[1] for p in waypoints]

    # 선형 보간 기저 경로
    base = np.interp(np.arange(n + 1), times, prices)

    # Brownian bridge 노이즈 추가 (범위의 3% 진폭)
    noise_std = (high_p - low_p) * 0.03
    W = np.cumsum(rng.normal(0, noise_std, n + 1))
    bridge = W - np.linspace(W[0], W[-1], n + 1)  # 양 끝 0으로 고정

    path = base + bridge * 0.4
    path = np.clip(path, low_p, high_p)
    path[0] = open_p
    path[n] = close_p
    return path


def _path_to_ohlc(path, rng):
    """경로 포인트 → 1분봉 (open, high, low, close) 리스트"""
    n = len(path) - 1
    span = max(path) - min(path)
    noise_scale = span * 0.004

    candles = []
    for i in range(n):
        o = path[i]
        c = path[i + 1]
        wick = abs(rng.normal(0, noise_scale))
        h = max(o, c) + wick
        l = min(o, c) - wick
        candles.append((int(o), int(h), int(l), int(c)))
    return candles


def _volume_series(n, total, rng):
    """거래량 분배 (시초·종가 부근 집중)"""
    w = np.ones(n)
    w[:20]   *= 3.0   # 시초 집중
    w[-20:]  *= 2.0   # 마감 집중
    w *= rng.lognormal(0, 0.6, n)
    w /= w.sum()
    vols = (w * total).astype(int)
    vols[vols < 1] = 1
    return vols


# ================================================================== #
#  패턴 주입                                                           #
# ================================================================== #

def _make_hammer(box_low, atr, rng):
    """
    망치형 캔들 생성 (박스 저가 하방 이탈 + 긴 아래꼬리).
    조건: lower_wick/total ≥ 0.60, body/total ≤ 0.25, upper_wick/total ≤ 0.15
    """
    total      = atr * rng.uniform(0.45, 0.75)
    lower_frac = rng.uniform(0.65, 0.80)
    body_frac  = rng.uniform(0.05, 0.20)
    upper_frac = 1.0 - lower_frac - body_frac

    low    = box_low * (1 - rng.uniform(0.005, 0.02))   # 박스 하방
    bottom = low + total * lower_frac                    # 몸통 하단
    top    = bottom + total * body_frac                  # 몸통 상단
    high   = top + total * upper_frac

    close = rng.uniform(bottom, top)
    open_p = rng.uniform(bottom, top)
    return (int(open_p), int(high), int(low), int(close))


def _make_shooting_star(box_high, atr, rng):
    """역망치형(Shooting Star) 캔들 생성"""
    total      = atr * rng.uniform(0.45, 0.75)
    upper_frac = rng.uniform(0.65, 0.80)
    body_frac  = rng.uniform(0.05, 0.20)
    lower_frac = 1.0 - upper_frac - body_frac

    high   = box_high * (1 + rng.uniform(0.005, 0.02))
    top    = high - total * upper_frac
    bottom = top - total * body_frac
    low    = bottom - total * lower_frac

    close  = rng.uniform(bottom, top)
    open_p = rng.uniform(bottom, top)
    return (int(open_p), int(high), int(low), int(close))


def _inject_pattern(candles_9to10, box_high, box_low, atr, pattern_type, rng):
    """
    09:15 이후 candle 리스트에 패턴 삽입 후 자연스러운 회복 추가.
    pattern_type: 'hammer' | 'star'
    """
    n = len(candles_9to10)
    if n < 6:
        return candles_9to10

    pos = int(rng.integers(1, min(20, n - 4)))  # 삽입 위치

    if pattern_type == "hammer":
        pat = _make_hammer(box_low, atr, rng)
        recovery_target = box_low + atr * rng.uniform(0.3, 0.7)
        recovery_start  = pat[3]  # close
    else:
        pat = _make_shooting_star(box_high, atr, rng)
        recovery_target = box_high - atr * rng.uniform(0.3, 0.7)
        recovery_start  = pat[3]

    result = list(candles_9to10)
    result[pos] = pat

    # 패턴 이후 점진적 회복
    recovery_len = min(10, n - pos - 1)
    for j in range(1, recovery_len + 1):
        t  = j / recovery_len
        p  = recovery_start + t * (recovery_target - recovery_start)
        dk = atr * 0.015
        o  = p + rng.uniform(-dk, dk)
        c  = p + rng.uniform(-dk, dk)
        h  = max(o, c) + abs(rng.normal(0, dk))
        l  = min(o, c) - abs(rng.normal(0, dk))
        result[pos + j] = (int(o), int(h), int(l), int(c))

    return result


# ================================================================== #
#  하루치 분봉 생성                                                    #
# ================================================================== #

def generate_day(
    ticker: str,
    yyyymmdd: str,
    open_p: float,
    high_p: float,
    low_p:  float,
    close_p: float,
    volume: int,
    atr: float,
    prev_high: float,
    prev_low:  float,
) -> list[tuple]:
    """
    하루치 1분봉 (09:00~15:30, 390분) 생성.
    반환: [(time_str, open, high, low, close, volume), ...]
    """
    seed = int(ticker) * 10000 + int(yyyymmdd)
    rng  = np.random.default_rng(seed % (2 ** 32))

    # ── 전체 경로 생성 ──
    path = _price_path(N_MINUTES, open_p, close_p, high_p, low_p, rng)
    ohlc = _path_to_ohlc(path, rng)
    vols = _volume_series(N_MINUTES, volume, rng)

    # ── 패턴 주입 결정 ──
    inject = rng.random() < PATTERN_RATE
    if inject and atr > 0:
        # 첫 15분봉 박스 계산 (생성된 09:00~09:14 캔들 기반)
        first15 = ohlc[:15]
        box_high_gen = max(c[1] for c in first15)
        box_low_gen  = min(c[2] for c in first15)

        # 패턴 종류 결정: 50/50
        ptype = "hammer" if rng.random() < 0.5 else "star"
        ohlc_9to10 = ohlc[15:90]  # 09:15~10:29
        ohlc_9to10 = _inject_pattern(
            ohlc_9to10, box_high_gen, box_low_gen, atr, ptype, rng
        )
        ohlc = ohlc[:15] + ohlc_9to10 + ohlc[90:]

    # ── 시각 문자열 생성 ──
    rows = []
    for i, ((o, h, l, c), vol) in enumerate(zip(ohlc, vols)):
        total_min = SESSION_START + i
        hh = total_min // 60
        mm = total_min % 60
        rows.append((f"{hh:02d}{mm:02d}00", o, h, l, c, vol))

    return rows


# ================================================================== #
#  ATR 계산 (일봉 기반)                                               #
# ================================================================== #

def _calc_atr(ohlcv: pd.DataFrame, idx: int, period: int = 14) -> float:
    if idx < period + 1:
        return 0.0
    trs = []
    for i in range(idx - period, idx):
        h  = ohlcv.iloc[i]["high"]
        l  = ohlcv.iloc[i]["low"]
        pc = ohlcv.iloc[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs))


# ================================================================== #
#  저장                                                                #
# ================================================================== #

def save_csv(ticker: str, yyyymmdd: str, rows: list[tuple]) -> None:
    out_dir  = DATA_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{ticker}_{yyyymmdd}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)


# ================================================================== #
#  메인                                                                #
# ================================================================== #

def run(tickers: list[str], start: str, end: str) -> None:
    logger.info(f"합성 분봉 생성 시작: {tickers}  {start}~{end}")
    logger.info("⚠ 합성 데이터입니다. 전략 로직 검증 용도로만 사용하세요.")

    for ticker in tickers:
        logger.info(f"\n[{ticker}] 일봉 다운로드 중...")
        ohlcv = load_stock_ohlcv(ticker, start, end)
        if ohlcv.empty:
            logger.warning(f"[{ticker}] 데이터 없음, 건너뜀")
            continue

        total = len(ohlcv)
        generated = 0

        for i, (date_idx, row) in enumerate(ohlcv.iterrows()):
            yyyymmdd = date_idx.strftime("%Y%m%d")
            atr = _calc_atr(ohlcv, i)

            prev_high = float(ohlcv.iloc[i - 1]["high"])  if i > 0 else float(row["high"])
            prev_low  = float(ohlcv.iloc[i - 1]["low"])   if i > 0 else float(row["low"])

            rows = generate_day(
                ticker   = ticker,
                yyyymmdd = yyyymmdd,
                open_p   = float(row["open"]),
                high_p   = float(row["high"]),
                low_p    = float(row["low"]),
                close_p  = float(row["close"]),
                volume   = int(row["volume"]),
                atr      = atr,
                prev_high = prev_high,
                prev_low  = prev_low,
            )
            save_csv(ticker, yyyymmdd, rows)
            generated += 1

            if generated % 50 == 0 or generated == total:
                logger.info(f"  [{ticker}] {generated}/{total} 완료 ({yyyymmdd})")

        logger.info(f"[{ticker}] {generated}일치 CSV 생성 완료 → backtest/data/{ticker}/")


def main() -> None:
    parser = argparse.ArgumentParser(description="분봉 합성 CSV 생성기")
    parser.add_argument("--tickers", nargs="+",
                        default=["005930", "000660", "068270"],
                        help="종목코드 (기본: 삼성전자 SK하이닉스 셀트리온)")
    parser.add_argument("--start",  default="20230101", help="시작일 YYYYMMDD")
    parser.add_argument("--end",    default="20241231", help="종료일 YYYYMMDD")
    args = parser.parse_args()

    run(args.tickers, args.start, args.end)


if __name__ == "__main__":
    main()
