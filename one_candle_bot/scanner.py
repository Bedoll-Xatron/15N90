"""
원캔들 단타 신호 스캐너

매매 없이 신호만 출력합니다.
텔레그램 봇이 .env에 설정되어 있으면 알림도 전송합니다.

사용법:
  python scanner.py           # 실시간 감시 (09:15 ~ 10:30)
  python scanner.py --now     # 지금 즉시 오늘 신호 확인 (장 중 아무 때나)
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import STRATEGY, UNIVERSE, load_kis_config
from market.api_client import KISClient
from market.universe import UniverseScreener
from market.holidays import get_calendar
from market.data_processor import (
    BoxRange, aggregate_candles, calc_atr, calc_avg_daily_volume,
    candle_to_box, get_first_15m_candle, parse_minute_candles,
)
from backtest.data_loader import load_stock_ohlcv
from backtest.engine import _daily_to_atr_rows, _daily_to_vol_rows, BacktestParams
from backtest.engine import _detect_signal_with_params
from strategy.filters import check_atr_filter, check_volume_filter, check_market_direction
from notify.telegram import send_signal, send_summary

# ── 감시 종목 (기본값) ───────────────────────────────────
DEFAULT_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "068270": "셀트리온",
}

PARAMS = BacktestParams()
BOX_CLOSE_TIME  = "091500"  # 첫 15분봉 마감
SCAN_END_TIME   = "103000"  # 신규 진입 마감
POLL_INTERVAL   = 60        # 초 (1분마다 폴링)


# ================================================================== #
#  핵심 스캔 로직                                                      #
# ================================================================== #

class StockContext:
    """종목별 당일 컨텍스트"""
    def __init__(self, ticker: str, name: str):
        self.ticker = ticker
        self.name   = name
        self.atr:       float          = 0.0
        self.avg_vol:   float          = 0.0
        self.box:       BoxRange | None = None
        self.signaled:  bool           = False   # 당일 신호 이미 발생


def _load_daily_context(ctx: StockContext, today: str) -> bool:
    """일봉 데이터로 ATR·평균거래량 사전 계산"""
    start  = "20230101"
    ohlcv  = load_stock_ohlcv(ctx.ticker, start, today)
    if ohlcv.empty or len(ohlcv) < PARAMS.atr_period + 2:
        logger.warning(f"[{ctx.ticker}] 일봉 데이터 부족")
        return False

    n = len(ohlcv)
    atr_rows = _daily_to_atr_rows(ohlcv.iloc[n - PARAMS.atr_period - 1: n])
    try:
        ctx.atr = calc_atr(atr_rows, PARAMS.atr_period)
    except ValueError:
        return False

    vol_rows  = _daily_to_vol_rows(ohlcv.iloc[max(0, n - 21): n])
    ctx.avg_vol = calc_avg_daily_volume(vol_rows, 20)
    return True


def _fetch_candles(client: KISClient, ticker: str, until: str) -> list:
    """KIS API → parse_minute_candles 변환"""
    try:
        raw = client.get_minute_ohlcv(ticker, until)
        return parse_minute_candles(raw)
    except Exception as e:
        logger.warning(f"[{ticker}] 분봉 조회 실패 ({until}): {e}")
        return []


def _setup_box(ctx: StockContext, client: KISClient) -> bool:
    """09:15 첫 15분봉 박스 설정 + 필터 적용"""
    candles  = _fetch_candles(client, ctx.ticker, BOX_CLOSE_TIME)
    first15  = get_first_15m_candle(candles)
    if first15 is None:
        logger.debug(f"[{ctx.ticker}] 첫 15분봉 없음")
        return False

    box = candle_to_box(first15)

    # ATR 필터
    atr_r = check_atr_filter(box.size, ctx.atr, PARAMS.atr_ratio)
    if not atr_r.passed:
        logger.info(f"[{ctx.ticker}] ATR 탈락: {atr_r.reason}")
        return False

    # 거래량 필터 (15m vs 일평균/26)
    vol_r = check_volume_filter(first15.volume, ctx.avg_vol / 26, PARAMS.vol_mult)
    if not vol_r.passed:
        logger.info(f"[{ctx.ticker}] 거래량 탈락: {vol_r.reason}")
        return False

    ctx.box = box
    logger.info(
        f"[{ctx.ticker}] 박스 확정  "
        f"H:{box.high:,}  L:{box.low:,}  크기:{box.size:,.0f}  "
        f"ATR비율:{box.size/ctx.atr:.1%}"
    )
    return True


def _check_signals(
    ctx: StockContext,
    client: KISClient,
    mkt_kospi: float,
    mkt_kosdaq: float,
) -> bool:
    """최신 5분봉 패턴 감지. 신호 발생 시 True."""
    if ctx.box is None or ctx.signaled:
        return False

    now_str  = datetime.now().strftime("%H%M%S")
    candles  = _fetch_candles(client, ctx.ticker, now_str)
    if not candles:
        return False

    monitoring = [c for c in candles if BOX_CLOSE_TIME <= c.time <= SCAN_END_TIME]
    five_min   = aggregate_candles(monitoring, 5)

    mkt_dir = check_market_direction(mkt_kospi, mkt_kosdaq, PARAMS.market_pct)

    for j in range(1, len(five_min)):
        curr = five_min[j]
        prev = five_min[j - 1]
        sig  = _detect_signal_with_params(curr, prev, ctx.box, PARAMS)
        if sig is None:
            continue
        if not mkt_dir.allows(sig.direction):
            logger.info(f"[{ctx.ticker}] 시장 방향 필터로 {sig.direction.value} 차단")
            continue

        send_signal(
            ticker      = ctx.ticker,
            name        = ctx.name,
            direction   = sig.direction.value,
            pattern     = sig.pattern.value,
            entry       = sig.trigger_price,
            stop        = sig.stop_loss,
            tp          = sig.take_profit,
            rr          = sig.rr_ratio,
            candle_time = sig.candle_time,
        )
        ctx.signaled = True
        return True

    return False


def _get_market_change(client: KISClient) -> tuple[float, float]:
    """KOSPI·KOSDAQ 당일 등락률 조회 (pykrx 기반, KIS API fallback)"""
    today = date.today().strftime("%Y%m%d")
    try:
        from backtest.data_loader import load_market_proxy
        mkt = load_market_proxy(today, today)
        if not mkt.empty:
            row = mkt.iloc[-1]
            return float(row["kospi_chg"]), float(row["kosdaq_chg"])
    except Exception:
        pass

    # fallback: KIS API 현재가 조회 (ETF는 500 오류 발생 가능)
    try:
        k200  = client.get_stock_price("069500")
        kq150 = client.get_stock_price("229200")
        kospi  = float(k200.get("prdy_ctrt",  "0"))
        kosdaq = float(kq150.get("prdy_ctrt", "0"))
        return kospi, kosdaq
    except Exception as e:
        logger.warning(f"시장 방향 조회 실패 (중립 적용): {e}")
        return 0.0, 0.0


# ================================================================== #
#  모드별 실행                                                         #
# ================================================================== #

def run_now(client: KISClient, tickers: dict) -> None:
    """--now: 지금 즉시 오늘 신호 확인"""
    today = date.today().strftime("%Y%m%d")
    logger.info(f"즉시 스캔 시작  {today}")

    ctxs: list[StockContext] = []
    for ticker, name in tickers.items():
        ctx = StockContext(ticker, name)
        if _load_daily_context(ctx, today):
            ctxs.append(ctx)

    kospi, kosdaq = _get_market_change(client)
    logger.info(f"시장 방향  KOSPI {kospi:+.2f}%  KOSDAQ {kosdaq:+.2f}%")

    signal_count = 0
    for ctx in ctxs:
        if _setup_box(ctx, client):
            if _check_signals(ctx, client, kospi, kosdaq):
                signal_count += 1

    send_summary(today, len(ctxs), signal_count)


def run_realtime(client: KISClient, tickers: dict) -> None:
    """실시간 감시 (09:15 ~ 10:30)"""
    today = date.today().strftime("%Y%m%d")
    logger.info(f"실시간 스캔 대기  {today}")

    # ── 사전 준비 ──
    ctxs: list[StockContext] = []
    for ticker, name in tickers.items():
        ctx = StockContext(ticker, name)
        if _load_daily_context(ctx, today):
            ctxs.append(ctx)
    logger.info(f"준비 완료: {len(ctxs)}종목")

    # ── 09:15 대기 ──
    _wait_until("091500", "첫 15분봉 마감")

    kospi, kosdaq = _get_market_change(client)
    logger.info(f"시장 방향  KOSPI {kospi:+.2f}%  KOSDAQ {kosdaq:+.2f}%")

    active = [ctx for ctx in ctxs if _setup_box(ctx, client)]
    logger.info(f"박스 확정: {len(active)}종목 감시 시작")

    if not active:
        logger.info("감시 대상 없음 — 종료")
        send_summary(today, len(ctxs), 0)
        return

    # ── 09:15 ~ 10:30 폴링 ──
    signal_count = 0
    while _now_str() <= SCAN_END_TIME:
        for ctx in active:
            if _check_signals(ctx, client, kospi, kosdaq):
                signal_count += 1
        time.sleep(POLL_INTERVAL)

    logger.info("10:30 — 신규 진입 마감")
    send_summary(today, len(ctxs), signal_count)


def _now_str() -> str:
    return datetime.now().strftime("%H%M%S")


def _wait_until(target: str, label: str) -> None:
    while _now_str() < target:
        remaining = _seconds_until(target)
        logger.info(f"{label} 대기 중... {remaining//60}분 {remaining%60}초 남음")
        time.sleep(min(60, remaining))
    logger.info(f"{label} 도달")


def _seconds_until(target_hhmm: str) -> int:
    now = datetime.now()
    th, tm = int(target_hhmm[:2]), int(target_hhmm[2:4])
    target = now.replace(hour=th, minute=tm, second=0, microsecond=0)
    diff = int((target - now).total_seconds())
    return max(0, diff)


# ================================================================== #
#  진입점                                                              #
# ================================================================== #

def _announce_holiday(today: date, cal) -> None:
    """휴장일 — 콘솔 로그만 출력하고 종료"""
    names = cal.holiday_names(today.year, today.month)
    name  = names.get(today.strftime("%Y%m%d"), "주말")
    next_td = cal.next_trading_day(today)
    logger.info(f"휴장일: {today} ({name})  다음 영업일: {next_td}")


def _build_universe(client: KISClient, args) -> dict[str, str]:
    """감시 종목 결정 — 명시적 tickers > Universe 스크리닝 > 기본값"""
    if args.tickers:
        return {t: t for t in args.tickers}

    logger.info(f"Universe 스크리닝 시작 (상위 {args.limit}종목)...")
    try:
        screener = UniverseScreener()
        result   = screener.screen(limit=args.limit)
        if result:
            return result
        logger.warning("Universe 스크리닝 결과 없음 → 기본 종목 사용")
    except Exception as e:
        logger.warning(f"Universe 스크리닝 실패 ({e}) → 기본 종목 사용")

    return DEFAULT_TICKERS


def main() -> None:
    parser = argparse.ArgumentParser(description="원캔들 신호 스캐너 (매매 없음)")
    parser.add_argument("--now",     action="store_true", help="즉시 신호 확인")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="감시 종목코드 직접 지정 (예: 005930 000660)")
    parser.add_argument("--limit",   type=int, default=8,
                        help="Universe 최대 종목 수 (기본 8)")
    args = parser.parse_args()

    try:
        cfg    = load_kis_config()
        client = KISClient(cfg)
    except EnvironmentError as e:
        print(f"[오류] {e}\n.env 파일에 KIS_APP_KEY / KIS_APP_SECRET 를 입력하세요.")
        sys.exit(1)

    # ── 휴장일 체크 ──
    cal   = get_calendar()
    today = date.today()
    if not args.now and not cal.is_trading_day(today):
        _announce_holiday(today, cal)
        return

    tickers = _build_universe(client, args)
    logger.info(f"감시 종목 {len(tickers)}개 확정")

    if args.now:
        run_now(client, tickers)
    else:
        run_realtime(client, tickers)


if __name__ == "__main__":
    main()
