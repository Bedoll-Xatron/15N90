import argparse
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import load_kis_config
from market.api_client import KISClient
from market.universe import UniverseScreener
from market.news_fetcher import fetch_recent_news
from ai.analyzer import NIMAnalyzer

# AI 클라이언트 전역 초기화
ai_analyzer = NIMAnalyzer()
from market.holidays import get_calendar
from market.data_processor import (
    BoxRange, aggregate_candles, calc_atr, calc_avg_daily_volume,
    candle_to_box, get_first_15m_candle, parse_minute_candles,
)
from backtest.data_loader import load_stock_ohlcv
from backtest.engine import _daily_to_atr_rows, _daily_to_vol_rows, BacktestParams
from strategy.filters import check_atr_filter, check_volume_filter, check_market_direction
from strategy.position_sizer import calc_position_size
from strategy.pattern import detect_entry_signal as detect_strategy_A, detect_strategy_B, detect_strategy_C, detect_strategy_D

from notify.telegram import (
    send_mock_buy,
    send_mock_sell,
    send_daily_report,
    check_commands,
    send as send_telegram
)
from ai.report_generator import generate_daily_report

from mock_trade.portfolio import Portfolio, Position
from mock_trade.position_manager import PositionManager
from risk.daily_limit import DailyLimitManager


DEFAULT_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "068270": "셀트리온",
    "005380": "현대차",
    "000270": "기아",
    "105560": "KB금융",
    "035420": "NAVER",
    "035720": "카카오",
    "051910": "LG화학",
    "005490": "POSCO홀딩스",
    "066570": "LG전자",
    "028260": "삼성물산",
    "032830": "삼성생명",
    "012330": "현대모비스",
    "373220": "LG에너지솔루션",
}

PARAMS = BacktestParams()
BOX_CLOSE_TIME  = "091500"
SCAN_END_TIME   = "103000"
MARKET_CLOSE_TIME = "145000"
POLL_INTERVAL   = 60


class StockContext:
    def __init__(self, ticker: str, name: str):
        self.ticker = ticker
        self.name   = name
        self.atr:         float          = 0.0
        self.avg_vol:     float          = 0.0
        self.prev_close:  float          = 0.0
        self.kijun_sen:   float          = 0.0
        self.box:         BoxRange | None = None
        self.box_rejected: bool = False
        self.signaled_A:  bool = False
        self.signaled_B:  bool = False
        self.signaled_C:  bool = False
        self.signaled_D:  bool = False
        # 분봉 캐시: API 중복 호출 최소화를 위한 증분 업데이트 용
        self._cached_candles: list = []   # 지금까지 수신된 모든 분봉
        self._last_candle_time: str = ""  # 마지막으로 받은 분봉 시각


def _load_daily_context(ctx: StockContext, today: str) -> bool:
    start  = "20230101"
    ohlcv  = load_stock_ohlcv(ctx.ticker, start, today)
    if ohlcv.empty or len(ohlcv) < PARAMS.atr_period + 2:
        return False

    ctx.prev_close = float(ohlcv["close"].iloc[-1])
    n = len(ohlcv)
    
    # 일목균형표 기준선(26일 최고가와 최저가의 중간값) 계산
    if n >= 26:
        recent_26 = ohlcv.iloc[-26:]
        highest_high = float(recent_26["high"].max())
        lowest_low = float(recent_26["low"].min())
        ctx.kijun_sen = (highest_high + lowest_low) / 2
    else:
        ctx.kijun_sen = 0.0
        
    atr_rows = _daily_to_atr_rows(ohlcv.iloc[n - PARAMS.atr_period - 1: n])
    try:
        ctx.atr = calc_atr(atr_rows, PARAMS.atr_period)
    except ValueError:
        return False

    vol_rows  = _daily_to_vol_rows(ohlcv.iloc[max(0, n - 21): n])
    ctx.avg_vol = calc_avg_daily_volume(vol_rows, 20)
    return True


def _fetch_candles(client: KISClient, ticker: str, until: str) -> list:
    try:
        raw = client.get_minute_ohlcv(ticker, until)
        return parse_minute_candles(raw)
    except Exception as e:
        logger.warning(f"[{ticker}] 분봉 조회 실패 ({until}): {e}")
        return []


def _setup_box(ctx: StockContext, client: KISClient) -> bool:
    candles  = _fetch_candles(client, ctx.ticker, BOX_CLOSE_TIME)
    first15  = get_first_15m_candle(candles)
    if first15 is None:
        return False

    box = candle_to_box(first15)
    
    from config import STRATEGY
    
    # ── 갭 상승 필터 (전일 종가 대비 시가 갭이 max_gap_pct 초과 시 탈락) ──
    if ctx.prev_close > 0:
        gap_pct = (first15.open / ctx.prev_close - 1) * 100
        if gap_pct > STRATEGY.max_gap_pct:
            logger.info(f"[{ctx.ticker}] 갭 상승 {gap_pct:.1f}% 초과로 박스 거부")
            ctx.box_rejected = True
            return False

    atr_r = check_atr_filter(box.size, ctx.atr, PARAMS.atr_ratio)
    if not atr_r.passed:
        ctx.box_rejected = True
        return False

    # ── 거래량 폭발 필터 (15분만에 일평균 거래량의 box_vol_ratio 터졌는지 확인) ──
    if ctx.avg_vol > 0 and first15.volume < ctx.avg_vol * STRATEGY.box_vol_ratio:
        ctx.box_rejected = True
        return False
        
    # ── AI 뉴스 검증 (악재 필터링) ──
    if ai_analyzer.is_available():
        headlines = fetch_recent_news(ctx.ticker, limit=5)
        if headlines:
            # 뉴스가 있을 경우 AI 판별
            passed = ai_analyzer.analyze_news_catalyst(ctx.ticker, ctx.name, headlines)
            if not passed:
                logger.info(f"[{ctx.ticker}] AI 판별 결과 악재 감지로 박스 추적 거부")
                ctx.box_rejected = True
                return False

    ctx.box = box
    logger.info(f"[{ctx.ticker}] 박스 확정 H:{box.high:,} L:{box.low:,} ATR비율:{box.size/ctx.atr:.1%}")
    return True


def _execute_mock_buy(
    strategy_id: str,
    ctx: StockContext,
    sig,
    portfolio: Portfolio,
    limit_mgr: DailyLimitManager,
    locked_tickers: set,
    initial_balance: float,          # 포지션 사이징의 기준: 전체 자본의 1%
):
    """매수 실행 (일일 한도 및 전략 간 종목 중복 방지 포함)"""
    # ① 일일 손실 한도 초과 시 진입 차단
    if not limit_mgr.can_enter():
        logger.warning(f"[전략 {strategy_id}] 일일 한도 초과로 {ctx.ticker} 진입 차단")
        return

    # ② 다른 전략이 이미 같은 종목 매수 중이면 차단 (집중 리스크 방지)
    if ctx.ticker in locked_tickers:
        logger.info(f"[전략 {strategy_id}] {ctx.ticker} 다른 전략이 보유 중 → 진입 스킵")
        return

    # ③ 주식단테 기법: 기준선 지지 부근(±3%) 타점이면 비중 2배 베팅 (Risk 1% -> 2%)
    current_risk_pct = 0.01
    is_kijun_bounce = False
    if ctx.kijun_sen > 0:
        dist_to_kijun = abs(sig.trigger_price - ctx.kijun_sen) / ctx.kijun_sen
        if dist_to_kijun <= 0.03:
            current_risk_pct = 0.02
            is_kijun_bounce = True
            logger.info(f"[{strategy_id}] {ctx.ticker} 기준선 지지 구간! 비중 2배 베팅 (Risk {current_risk_pct*100}%)")

    # ④ 퀀트 기법: 시간 가치 감가상각 (Time Decay Penalty)
    # 장 후반일수록 돌파 승률이 떨어지므로 리스크를 축소함
    if sig.candle_time:
        try:
            hh, mm = int(sig.candle_time[:2]), int(sig.candle_time[2:4])
            mins_from_open = (hh - 9) * 60 + mm
            
            if mins_from_open < 15:
                decay_multiplier = 1.0
            elif mins_from_open < 30:
                decay_multiplier = 0.8
            elif mins_from_open < 45:
                decay_multiplier = 0.6
            else:
                decay_multiplier = 0.4
                
            if decay_multiplier < 1.0:
                current_risk_pct *= decay_multiplier
                logger.info(f"[{strategy_id}] {ctx.ticker} 시간 감가 적용: {sig.candle_time} -> 비중 {decay_multiplier*100}% 축소")
        except:
            pass

    try:
        ps = calc_position_size(
            equity=initial_balance,   # 포지션 사이징: 현금잔고 아닌 당일 시작 총 자본 기준
            entry_price=sig.trigger_price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            risk_pct=current_risk_pct,
            max_invest_pct=0.20
        )
    except Exception as e:
        logger.error(f"[{strategy_id}] 사이즈 계산 실패: {e}")
        return

    if portfolio.buy(
        ticker=ctx.ticker,
        name=ctx.name,
        direction=sig.direction.value,
        price=sig.trigger_price,
        quantity=ps.shares,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit
    ):
        locked_tickers.add(ctx.ticker)
        
        # 알림용 패턴 이름 수정
        pattern_msg = sig.pattern if not is_kijun_bounce else f"{sig.pattern} (💡기준선 지지 베팅!)"
        
        send_mock_buy(
            strategy_id=strategy_id,
            ticker=ctx.ticker,
            name=ctx.name,
            direction=sig.direction.value,
            price=sig.trigger_price,
            qty=ps.shares,
            cost=ps.invest_amount,
            pattern=pattern_msg
        )

def _fetch_candles_incremental(client: KISClient, ctx: StockContext) -> list:
    """
    분봉을 증분 방식으로 가져옵니다.
    - 첫 호출: 전체 조회
    - 이후: 마지막 수신 시각 이후 새 분봉만 데이터에 추가
    """
    now_str = datetime.now().strftime("%H%M%S")
    new_candles = _fetch_candles(client, ctx.ticker, now_str)
    
    if not ctx._cached_candles:
        ctx._cached_candles = new_candles
    else:
        # 마지막 캐시 시각 이후의 새 선 데이터만 추가
        new_only = [c for c in new_candles if c.time > ctx._last_candle_time]
        ctx._cached_candles.extend(new_only)
    
    if ctx._cached_candles:
        ctx._last_candle_time = ctx._cached_candles[-1].time
    
    return ctx._cached_candles


def _check_strategies(
    ctx: StockContext,
    client: KISClient,
    mkt_kospi: float,
    mkt_kosdaq: float,
    portfolios: dict[str, Portfolio],
    limit_mgrs: dict[str, DailyLimitManager],
    locked_tickers: set,
    initial_balances: dict[str, float],
):
    if ctx.box is None:
        return

    # 증분 캐시에서 분봉 가져오기 (API 호출 최소화)
    all_candles = _fetch_candles_incremental(client, ctx)
    if not all_candles:
        return

    monitoring = [c for c in all_candles if BOX_CLOSE_TIME <= c.time <= SCAN_END_TIME]
    five_min   = aggregate_candles(monitoring, 5)
    
    if len(five_min) < 2:
        return

    curr = five_min[-1]
    prev = five_min[-2]

    # ④ 퀀트 기법: 당일 VWAP(거래량 가중 평균가) 방어선
    # 당일 모든 분봉 기준 VWAP 계산
    total_vol = sum(c.volume for c in all_candles)
    if total_vol > 0:
        vwap = sum(c.close * c.volume for c in all_candles) / total_vol
        if curr.close < vwap:
            # 기관의 평균단가(VWAP) 아래에서 노는 종목은 즉각 버림
            return

    # ④ 퀀트 기법: 시장 상대강도 (Index Relative Strength) 필터
    if ctx.prev_close > 0:
        stock_pct = (curr.close / ctx.prev_close) - 1.0
        # 코스피/코스닥 중 더 강한 지수의 상승률 (최소 0%)
        mkt_max_pct = max(mkt_kospi / 100.0, mkt_kosdaq / 100.0, 0.0)
        is_stronger_than_market = stock_pct >= mkt_max_pct
    else:
        is_stronger_than_market = True

    # 시장 방향: 호출 시점의 최신 파라미터 사용 (루프마다 갱신된 값)
    mkt_dir = check_market_direction(mkt_kospi, mkt_kosdaq, PARAMS.market_pct)

    # Strategy A
    if not ctx.signaled_A:
        sig_a = detect_strategy_A(curr, prev, ctx.box)
        if sig_a and mkt_dir.allows(sig_a.direction):
            ctx.signaled_A = True
            
            # AI 패턴 승인 확인
            approved = True
            if ai_analyzer.is_available():
                ohlcv_text = "\\n".join([f"Time:{c.time} O:{c.open} H:{c.high} L:{c.low} C:{c.close} Vol:{c.volume}" for c in five_min[-5:]])
                approved = ai_analyzer.validate_pattern_context(ctx.ticker, "A (휩소)", ohlcv_text)
                
            if approved:
                logger.info(f"[{ctx.ticker}] 전략 A 신호 포착 및 AI 승인 완료")
                _execute_mock_buy("A", ctx, sig_a, portfolios["A"], limit_mgrs["A"], locked_tickers, initial_balances["A"])

    # Strategy B (돌파) - 지수보다 강할 때만
    if not ctx.signaled_B:
        sig_b = detect_strategy_B(curr, prev, ctx.box)
        if sig_b and mkt_dir.allows(sig_b.direction) and is_stronger_than_market:
            ctx.signaled_B = True
            
            # AI 패턴 승인 확인
            approved = True
            if ai_analyzer.is_available():
                ohlcv_text = "\\n".join([f"Time:{c.time} O:{c.open} H:{c.high} L:{c.low} C:{c.close} Vol:{c.volume}" for c in five_min[-5:]])
                approved = ai_analyzer.validate_pattern_context(ctx.ticker, "B (돌파)", ohlcv_text)
                
            if approved:
                logger.info(f"[{ctx.ticker}] 전략 B 신호 포착 및 AI 승인 완료")
                _execute_mock_buy("B", ctx, sig_b, portfolios["B"], limit_mgrs["B"], locked_tickers, initial_balances["B"])

    # Strategy C (눌림목) - 지수보다 강할 때만
    if not ctx.signaled_C:
        sig_c = detect_strategy_C(five_min, ctx.box)
        if sig_c and mkt_dir.allows(sig_c.direction) and is_stronger_than_market:
            ctx.signaled_C = True
            
            # AI 패턴 승인 확인
            approved = True
            if ai_analyzer.is_available():
                ohlcv_text = "\\n".join([f"Time:{c.time} O:{c.open} H:{c.high} L:{c.low} C:{c.close} Vol:{c.volume}" for c in five_min[-5:]])
                approved = ai_analyzer.validate_pattern_context(ctx.ticker, "C (눌림목)", ohlcv_text)
                
            if approved:
                logger.info(f"[{ctx.ticker}] 전략 C 신호 포착 및 AI 승인 완료")
                _execute_mock_buy("C", ctx, sig_c, portfolios["C"], limit_mgrs["C"], locked_tickers, initial_balances["C"])

    # Strategy D (시초가 갭 5% 미만에서 시가 돌파) - 지수보다 강할 때만
    if not ctx.signaled_D:
        sig_d = detect_strategy_D(monitoring) # 1분봉 원본 배열을 넘김
        if sig_d and mkt_dir.allows(sig_d.direction) and is_stronger_than_market:
            ctx.signaled_D = True
            
            # AI 패턴 승인 확인
            approved = True
            if ai_analyzer.is_available():
                # 전략 D는 1분봉 시가 회복이므로 최근 1분봉 5개를 보냄
                ohlcv_text = "\\n".join([f"Time:{c.time} O:{c.open} H:{c.high} L:{c.low} C:{c.close} Vol:{c.volume}" for c in monitoring[-5:]])
                approved = ai_analyzer.validate_pattern_context(ctx.ticker, "D (시가 회복)", ohlcv_text)
                
            if approved:
                logger.info(f"[{ctx.ticker}] 전략 D 신호 포착 및 AI 승인 완료")
                _execute_mock_buy("D", ctx, sig_d, portfolios["D"], limit_mgrs["D"], locked_tickers, initial_balances["D"])


def _handle_telegram_commands(portfolios: dict, limit_mgrs: dict):
    """텔레그램에서 수신된 명령어를 처리합니다."""
    cmds = check_commands()
    for text in cmds:
        if text.startswith("/status"):
            lines = ["🤖 <b>현재 봇 상태 보고</b>"]
            for s_id, p in portfolios.items():
                pos_count = len(p.positions)
                lines.append(f"<b>[전략 {s_id}]</b> 보유: {pos_count}종목 / 잔고: {p.balance:,.0f}원")
                for t, pos in p.positions.items():
                    lines.append(f"  - {pos.name}: {pos.direction} {pos.quantity}주 @ {pos.entry_price:,.0f}")
                lines.append(f"  - 일일 한도 차단: {'✅ 차단됨' if limit_mgrs[s_id].halted else '❌ 해제상태'}")
            send_telegram("\n".join(lines))
            
        elif text.startswith("/test"):
            send_telegram("✅ 원캔들 봇이 정상적으로 작동 중이며, 명령어를 성공적으로 수신했습니다!")


def _get_market_change(client: KISClient) -> tuple[float, float]:
    today = date.today().strftime("%Y%m%d")
    try:
        from backtest.data_loader import load_market_proxy
        mkt = load_market_proxy(today, today)
        if not mkt.empty:
            row = mkt.iloc[-1]
            return float(row["kospi_chg"]), float(row["kosdaq_chg"])
    except Exception:
        pass

    try:
        k200  = client.get_stock_price("069500")
        kq150 = client.get_stock_price("229200")
        return float(k200.get("prdy_ctrt", "0")), float(kq150.get("prdy_ctrt", "0"))
    except Exception:
        return 0.0, 0.0

def _check_market_ema21(client: KISClient) -> bool:
    """코스피(KODEX 200)의 일봉 21 EMA가 상승 추세(V자 우측)인지 확인"""
    today = date.today().strftime("%Y%m%d")
    try:
        from backtest.data_loader import load_stock_ohlcv
        # KODEX 200 (069500)
        df = load_stock_ohlcv("069500", "20230101", today)
        if df.empty or len(df) < 22:
            return True # 데이터 부족 시 제한 안함
            
        df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
        recent = df.tail(2)
        
        is_rising = float(recent["ema21"].iloc[-1]) > float(recent["ema21"].iloc[-2])
        is_above = float(recent["close"].iloc[-1]) >= float(recent["ema21"].iloc[-1])
        
        return is_rising and is_above
    except Exception as e:
        logger.warning(f"시장 21 EMA 확인 실패: {e}")
        return True


def _now_str() -> str:
    return datetime.now().strftime("%H%M%S")

def _wait_until(target: str, label: str, portfolios: dict = None, limit_mgrs: dict = None) -> None:
    import time
    last_log = 0
    while _now_str() < target:
        remaining = _seconds_until(target)
        now_ts = time.time()
        if now_ts - last_log >= 60:
            logger.info(f"{label} 대기 중... {remaining//60}분 {remaining%60}초 남음")
            last_log = now_ts
            
        if portfolios and limit_mgrs:
            _handle_telegram_commands(portfolios, limit_mgrs)
            
        time.sleep(min(5, remaining))
    logger.info(f"{label} 도달")

def _seconds_until(target_hhmm: str) -> int:
    now = datetime.now()
    th, tm = int(target_hhmm[:2]), int(target_hhmm[2:4])
    target = now.replace(hour=th, minute=tm, second=0, microsecond=0)
    diff = int((target - now).total_seconds())
    return max(0, diff)


def _build_universe(client: KISClient, limit: int) -> dict[str, str]:
    logger.info(f"Universe 스크리닝 시작 (상위 {limit}종목)...")
    try:
        screener = UniverseScreener()
        result   = screener.screen(limit=limit, client=client)
        if result:
            return result
    except Exception as e:
        logger.warning(f"Universe 스크리닝 실패 ({e}) → 기본 종목 사용")
    return DEFAULT_TICKERS


def run_mock_trader(client: KISClient, limit: int):
    today = date.today().strftime("%Y%m%d")
    logger.info(f"모의투자 봇(A/B/C) 시작  {today}")

    # ── AI 매크로 동적 파라미터 튜닝 ──
    from market.data_processor import load_market_proxy
    from ai.macro_tuner import tune_daily_parameters
    from config import STRATEGY
    
    try:
        kospi = load_market_proxy("069500", "20230101", today)
        kosdaq = load_market_proxy("229200", "20230101", today)
        kospi_history = kospi["close"].tail(5).tolist() if len(kospi) >= 5 else []
        kosdaq_history = kosdaq["close"].tail(5).tolist() if len(kosdaq) >= 5 else []
        
        if kospi_history and kosdaq_history:
            tuned_params = tune_daily_parameters(kospi_history, kosdaq_history)
            if "box_vol_ratio" in tuned_params:
                STRATEGY.box_vol_ratio = tuned_params["box_vol_ratio"]
            if "target_rr" in tuned_params:
                STRATEGY.target_rr = tuned_params["target_rr"]
                
            logger.info(f"[AI 튜닝 완료] box_vol_ratio: {STRATEGY.box_vol_ratio}, target_rr: {STRATEGY.target_rr}")
    except Exception as e:
        logger.error(f"AI 매크로 튜닝 실패 (기본값 사용): {e}")

    data_dir = str(Path(__file__).parent / "mock_data")
    portfolios = {
        "A": Portfolio(strategy_id="A", data_dir=data_dir),
        "B": Portfolio(strategy_id="B", data_dir=data_dir),
        "C": Portfolio(strategy_id="C", data_dir=data_dir),
        "D": Portfolio(strategy_id="D", data_dir=data_dir),
    }
    
    stats = {
        "A": {"balance": portfolios["A"].balance, "pnl_today": 0.0, "trades_count": 0},
        "B": {"balance": portfolios["B"].balance, "pnl_today": 0.0, "trades_count": 0},
        "C": {"balance": portfolios["C"].balance, "pnl_today": 0.0, "trades_count": 0},
        "D": {"balance": portfolios["D"].balance, "pnl_today": 0.0, "trades_count": 0},
    }

    # 코스피 21 EMA 추세 확인 (하락장 리스크 관리)
    market_ema21_ok = _check_market_ema21(client)
    if not market_ema21_ok:
        logger.warning("🚨 [지수 리스크 필터] 코스피 지수가 21일 EMA 하락 추세(V자 좌측)입니다. 진입 비중(리스크 한도)을 절반으로 축소합니다.")
        risk_multiplier = 0.5
    else:
        logger.info("✅ [지수 리스크 필터] 코스피 지수가 21일 EMA 상승 추세(V자 우측)입니다. 정상 비중으로 진입합니다.")
        risk_multiplier = 1.0

    # 포지션 사이징 기준: 당일 시작 총 자본 고정 * risk_multiplier (하락장이면 절반)
    initial_balances = {
        "A": portfolios["A"].balance * risk_multiplier,
        "B": portfolios["B"].balance * risk_multiplier,
        "C": portfolios["C"].balance * risk_multiplier,
        "D": portfolios["D"].balance * risk_multiplier,
    }

    # 일일 손실 한도 매니저 (초기 잔고의 -2% 도달 시 신규 진입 차단)
    limit_mgrs = {
        "A": DailyLimitManager(initial_balances["A"], max_loss_pct=0.02, strategy_id="A"),
        "B": DailyLimitManager(initial_balances["B"], max_loss_pct=0.02, strategy_id="B"),
        "C": DailyLimitManager(initial_balances["C"], max_loss_pct=0.02, strategy_id="C"),
        "D": DailyLimitManager(initial_balances["D"], max_loss_pct=0.02, strategy_id="D"),
    }


    # 전략 간 중복 종목 매수 방지를 위한 글로벌 잠금 셋
    locked_tickers: set[str] = set()
    for portfolio in portfolios.values():
        for ticker in portfolio.positions.keys():
            locked_tickers.add(ticker)
    if locked_tickers:
        logger.info(f"기존 보유 종목 잠금 설정 (신규 진입 제외): {', '.join(locked_tickers)}")

    def make_on_sell(s_id):
        def on_sell(pos: Position, price: float, pnl: float, reason: str):
            stats[s_id]["trades_count"] += 1
            stats[s_id]["pnl_today"] += pnl
            stats[s_id]["balance"] = portfolios[s_id].balance
            limit_mgrs[s_id].record_pnl(pnl)     # 일일 한도 매니저에 손익 누적
            locked_tickers.discard(pos.ticker)    # 청산 후 잠금 해제
            send_mock_sell(s_id, pos.ticker, pos.name, price, pnl, reason)
        return on_sell

    pms = {
        "A": PositionManager(portfolios["A"], client, on_sell_callback=make_on_sell("A")),
        "B": PositionManager(portfolios["B"], client, on_sell_callback=make_on_sell("B")),
        "C": PositionManager(portfolios["C"], client, on_sell_callback=make_on_sell("C")),
        "D": PositionManager(portfolios["D"], client, on_sell_callback=make_on_sell("D")),
    }

    _wait_until(BOX_CLOSE_TIME, "첫 15분봉 마감", portfolios, limit_mgrs)

    # 09:15 직후 실시간 주도주 유니버스 추출
    tickers = _build_universe(client, limit)

    ctxs: list[StockContext] = []
    for ticker, name in tickers.items():
        ctx = StockContext(ticker, name)
        if _load_daily_context(ctx, today):
            ctxs.append(ctx)
    logger.info(f"준비 완료: {len(ctxs)}종목")

    kospi, kosdaq = _get_market_change(client)
    logger.info(f"초기 시장 방향 KOSPI {kospi:+.2f}% KOSDAQ {kosdaq:+.2f}%")

    active = ctxs
    for ctx in active:
        _setup_box(ctx, client)
    
    confirmed = len([c for c in active if c.box is not None])
    logger.info(f"박스 확정: {confirmed}종목 감시 시작 (실패 시 계속 재시도)")

    # 1. 09:15 ~ 10:30 (신호 감시 + 포지션 청산 감시)
    poll_count = 0
    while _now_str() <= SCAN_END_TIME:
        _handle_telegram_commands(portfolios, limit_mgrs)
        
        for pm in pms.values():
            pm.check_positions()

        # 시장 방향을 5분마다 갱신 (동적 업데이트)
        poll_count += 1
        if poll_count % 5 == 1:  # 첫 루프와 이후 5분마다
            kospi, kosdaq = _get_market_change(client)
            logger.debug(f"[시장 방향 갱신] KOSPI {kospi:+.2f}% KOSDAQ {kosdaq:+.2f}%")

        for ctx in active:
            if ctx.box_rejected:
                continue
            
            if ctx.box is None:
                if not _setup_box(ctx, client):
                    continue
                else:
                    logger.info(f"[{ctx.ticker}] 지연된 박스 확정 성공! 감시 합류")

            _check_strategies(ctx, client, kospi, kosdaq, portfolios, limit_mgrs, locked_tickers, initial_balances)

        # 모든 전략이 일일 한도 초과 시 신호 감시 조기 종료
        if all(lm.halted for lm in limit_mgrs.values()):
            logger.warning("모든 전략이 일일 손실 한도 도달 → 신호 감시 조기 종료")
            break
            
        time.sleep(POLL_INTERVAL)

    logger.info("10:30 — 신규 진입 마감")

    # 2. 10:30 ~ 14:50 (포지션 청산만 감시)
    while _now_str() <= MARKET_CLOSE_TIME:
        _handle_telegram_commands(portfolios, limit_mgrs)
        
        total_positions = sum(len(p.positions) for p in portfolios.values())
        if total_positions == 0:
            break
            
        for pm in pms.values():
            pm.check_positions()
            
        time.sleep(POLL_INTERVAL)

    # 3. 14:50 강제 청산
    for s_id, portfolio in portfolios.items():
        if len(portfolio.positions) > 0:
            logger.info(f"[전략 {s_id}] 장 마감. 남은 포지션을 강제 청산합니다.")
            pms[s_id].force_close_all()

    # 4. 일일 성과 리포트
    for s_id in stats:
        stats[s_id]["balance"] = portfolios[s_id].balance
    for lm in limit_mgrs.values():
        logger.info(lm.summary())
        
    logger.info("모의투자 종료. 텔레그램 성과 리포트 전송")
    send_daily_report(today, stats)
    
    # 5. AI 매매 복기 리포트 전송
    logger.info("AI 데일리 매매 복기 리포트 생성 중...")
    try:
        # 코스피/코스닥 당일 변동률 (간이 계산용, 실제로는 data_processor 등에서 가져옴)
        from market.data_processor import load_market_proxy
        kospi = load_market_proxy("069500", "20230101", today)
        kosdaq = load_market_proxy("229200", "20230101", today)
        kospi_chg = ((kospi["close"].iloc[-1] / kospi["close"].iloc[-2]) - 1) * 100 if len(kospi) > 1 else 0.0
        kosdaq_chg = ((kosdaq["close"].iloc[-1] / kosdaq["close"].iloc[-2]) - 1) * 100 if len(kosdaq) > 1 else 0.0
        
        # A, B, C 포트폴리오 중 하나(전체)의 히스토리 전달
        history_csv = str(portfolios["A"].history_file) 
        ai_report = generate_daily_report(history_csv, kospi_chg, kosdaq_chg)
        
        send_telegram(f"🤖 <b>[AI 데일리 매매 복기]</b>\n\n{ai_report}")
    except Exception as e:
        logger.error(f"AI 리포트 전송 중 오류: {e}")

def main() -> None:
    parser = argparse.ArgumentParser(description="원캔들 모의투자 봇 (A/B/C)")
    parser.add_argument("--limit", type=int, default=15, help="Universe 최대 종목 수")
    args = parser.parse_args()

    try:
        cfg = load_kis_config()
        client = KISClient(cfg)
    except EnvironmentError as e:
        print(f"[오류] {e}")
        sys.exit(1)

    cal = get_calendar()
    today = date.today()
    if not cal.is_trading_day(today):
        logger.info("오늘은 휴장일입니다. 실행을 종료합니다.")
        return

    run_mock_trader(client, args.limit)

if __name__ == "__main__":
    main()
