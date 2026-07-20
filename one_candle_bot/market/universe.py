"""
Universe 스크리너

메이저 주식 및 ETF를 대상으로, 현재 20일선 위에 있으면서 
최근 20거래일 수익률(모멘텀)이 가장 높은 종목들을 선별하여 
10개 미만의 당일 감시 종목을 선정합니다.
"""
import logging
from datetime import date
from typing import Dict

from config import UNIVERSE
from backtest.data_loader import load_stock_ohlcv
from market.holidays import get_calendar

logger = logging.getLogger(__name__)

# 절대 상폐되지 않을 시총 최상위 우량주 및 대표 ETF 모음
MAJOR_TICKERS = {
    # 메이저 KOSPI 우량주
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "000270": "기아",
    "068270": "셀트리온",
    "105560": "KB금융",
    "005490": "POSCO홀딩스",
    "035420": "NAVER",
    "035720": "카카오",
    "051910": "LG화학",
    "028260": "삼성물산",
    "006400": "삼성SDI",
    "012330": "현대모비스",
    "066570": "LG전자",
    "373220": "LG에너지솔루션",
    "032830": "삼성생명",
    "003550": "LG",
    "034730": "SK",
    "015760": "한국전력",
    "018260": "삼성SDS",
    "042700": "한미반도체",
    "034020": "두산에너빌리티",
    "011200": "HMM",
    "329180": "HD현대중공업",
    "323410": "카카오뱅크",
    "259960": "크래프톤",
    # 메이저 KOSDAQ 우량주
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "022100": "포스코DX",
    "066970": "엘앤에프",
    "028300": "HLB",
    "196170": "알테오젠",
    "068760": "셀트리온제약",
    "348370": "엔켐",
    "058470": "리노공업",
    "403870": "HPSP",
    "035900": "JYP Ent.",
    "041510": "에스엠",
    # 메이저 시장 지수 ETF (인버스/레버리지 제외 — 단타 세력 패턴 발생 구조 아님)
    "069500": "KODEX 200",
    # 메이저 테마/해외 ETF
    "381170": "TIGER 미국테크TOP10 INDXX",
    "381180": "TIGER 미국필라델피아반도체나스닥",
    "133690": "TIGER 미국나스닥100",
    "305720": "KODEX 2차전지산업",
    "091160": "KODEX 반도체",
    "364980": "TIGER KRX2차전지K-뉴딜",
}

def _get_recent_trading_day() -> str:
    """가장 최근 영업일 (공휴일·주말 제외)"""
    return get_calendar().last_trading_day().strftime("%Y%m%d")

class UniverseScreener:
    """종목 스크리너 (pykrx 기반, KIS API Fallback 지원)"""

    def _fetch_candidates_pykrx(self) -> Dict[str, str]:
        """Option 3: 시가총액 1,000억~1조원 필터링 후 거래대금 상위 추출"""
        from pykrx import stock as krx
        import pandas as pd
        from datetime import timedelta
        
        cal = get_calendar()
        today = cal.last_trading_day()
        yesterday = today - timedelta(days=1)
        while not cal.is_trading_day(yesterday):
            yesterday -= timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y%m%d")
        
        df_kq = krx.get_market_cap(yesterday_str, market="KOSDAQ")
        df_kp = krx.get_market_cap(yesterday_str, market="KOSPI")
        df = pd.concat([df_kq, df_kp])
        
        cond1 = df['시가총액'] >= 100_000_000_000
        cond2 = df['시가총액'] <= 1_000_000_000_000
        cond3 = df['거래대금'] >= 30_000_000_000
        
        filtered = df[cond1 & cond2 & cond3]
        filtered = filtered.sort_values(by='거래대금', ascending=False)
        
        candidates = {}
        for ticker in filtered.index:
            candidates[ticker] = krx.get_market_ticker_name(ticker)
            if len(candidates) >= 100:
                break
        
        if not candidates:
            raise ValueError("Pykrx 조회 결과 없음")
        return candidates

    def _fetch_candidates_kis(self, client) -> Dict[str, str]:
        """Option 2: KIS API 거래량 상위 연동"""
        if not client:
            raise ValueError("KIS Client가 제공되지 않았습니다.")
            
        candidates = {}
        kq_ranking = client.get_volume_ranking("Q", 50)
        kp_ranking = client.get_volume_ranking("J", 50)
        
        for item in kq_ranking + kp_ranking:
            code = item.get("mksc_shrn_iscd")
            name = item.get("hts_kor_isnm")
            if code and name:
                candidates[code] = name
        return candidates

    def _evaluate_base(self, base_dict: Dict[str, str], start_str: str, today_str: str) -> tuple[list, list]:
        """주어진 종목풀에 대해 필터링을 수행하고 (scored, fallback_scored) 반환"""
        scored = []
        fallback_scored = []
        for code, name in base_dict.items():
            try:
                df = load_stock_ohlcv(code, start_str, today_str)
                if df.empty or len(df) < 22:
                    continue

                # 일봉 21 EMA 계산
                df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
                
                # 최근 21일치 데이터 (오늘 포함)
                recent_df = df.tail(21)
                
                current_close = float(recent_df["close"].iloc[-1])
                ema21_current = float(recent_df["ema21"].iloc[-1])
                ema21_prev = float(recent_df["ema21"].iloc[-2])
                
                ma5 = recent_df["close"].tail(5).mean()
                
                # 20일 누적 수익률 (모멘텀)
                close_20_days_ago = float(recent_df["close"].iloc[0])
                if close_20_days_ago > 0:
                    momentum = (current_close / close_20_days_ago) - 1.0
                else:
                    momentum = 0.0
                    
                # 최근 거래대금 계산
                last = recent_df.iloc[-1]
                vol = float(last.get("volume", 0))
                trade_amt_est = vol * current_close
                
                # 1. 거래대금 500억 이상 (주도주)
                is_mega_volume = trade_amt_est >= UNIVERSE.min_avg_trade_amount
                
                # 2. 전일 거래량 2배 폭증 (매집봉)
                prev_19_days_vol = recent_df["volume"].iloc[:-1].mean()
                last_vol = float(recent_df["volume"].iloc[-1])
                is_volume_spike = (prev_19_days_vol > 0) and (last_vol >= prev_19_days_vol * 2.0)
                
                # [OR 조건] 거래대금이 500억 이상이거나, 전일 거래량이 2배 폭증했으면 통과
                if not (is_mega_volume or is_volume_spike):
                    continue
                    
                # 안전장치: 아무리 2배가 터졌어도 최소 유동성(100억) 미만인 잡주는 제외
                if trade_amt_est < 10_000_000_000:
                    continue
                    
                fallback_scored.append((code, name, momentum, trade_amt_est))
                
                # [크랙 트레이더의 21 EMA 필터 적용]
                # 1. 21 EMA가 상승 중이어야 함 (V자의 우측)
                if ema21_current <= ema21_prev:
                    continue
                    
                # 2. 현재 가격이 21 EMA 위에 있어야 함
                if current_close < ema21_current:
                    continue
                    
                # 3. 주식단테 기법: 주가가 5일 이동평균선(단기 생명선) 위에 있어야 함
                if current_close < ma5:
                    continue
                    
                scored.append((code, name, momentum, trade_amt_est))

            except Exception as e:
                logger.debug(f"[Universe] {code} 조회 실패: {e}")
                continue
                
        return scored, fallback_scored

    def screen(self, limit: int = 8, client=None) -> Dict[str, str]:
        """
        당일 감시 종목 반환 — {종목코드: 종목명}
        최근 20일 모멘텀 기준 상위 종목 추천 (MA20 이상 우상향 한정)
        client가 제공되면 당일 아침 실시간 등락률을 반영하여 최종 정렬합니다.
        """
        today_str  = _get_recent_trading_day()
        # 데이터 캐싱을 활용하므로 안전하게 넉넉히 가져옴
        start_str  = "20230101"

        logger.info(f"[Universe] 1차 스크리닝 시작 (대형주 {len(MAJOR_TICKERS)}종목)")
        scored, fallback_scored = self._evaluate_base(MAJOR_TICKERS, start_str, today_str)

        # 1차 대형주 검사 결과가 부족하면 2차 동적 발굴 시도
        if len(scored) < limit:
            logger.info(f"[Universe] 대형주 결과 부족({len(scored)}/{limit}). 동적 발굴을 추가합니다.")
            dynamic_base = {}
            try:
                dynamic_base = self._fetch_candidates_pykrx()
            except Exception as e:
                try:
                    dynamic_base = self._fetch_candidates_kis(client)
                except Exception as e2:
                    logger.warning(f"[Universe] 동적 발굴 실패: {e2}")
                    
            if dynamic_base:
                # 대형주 풀과 겹치지 않는 종목만 추출
                dynamic_base = {k: v for k, v in dynamic_base.items() if k not in MAJOR_TICKERS}
                logger.info(f"[Universe] 2차 스크리닝 시작 (동적 중소형주 {len(dynamic_base)}종목)")
                dyn_scored, dyn_fallback = self._evaluate_base(dynamic_base, start_str, today_str)
                
                scored.extend(dyn_scored)
                fallback_scored.extend(dyn_fallback)

        if not scored and fallback_scored:
            logger.warning("[Universe] 우상향 종목이 없어, 데이터 수집을 위해 거래대금이 터진 종목으로 대체합니다.")
            scored = fallback_scored

        # 모멘텀 내림차순 정렬 후 limit 적용
        if client is not None:
            logger.info("[Universe] 당일 아침 실시간 시세(KIS API)를 반영하여 최종 정렬합니다.")
            realtime_scored = []
            for code, name, mom, amt in scored:
                try:
                    price_data = client.get_stock_price(code)
                    today_chg = float(price_data.get("prdy_ctrt", "0"))
                    realtime_scored.append((code, name, mom, amt, today_chg))
                except Exception as e:
                    logger.debug(f"실시간 시세 조회 실패 ({code}): {e}")
                    realtime_scored.append((code, name, mom, amt, 0.0))
            
            # 정렬: 1순위 당일등락률, 2순위 20일모멘텀
            realtime_scored.sort(key=lambda x: (x[4], x[2]), reverse=True)
            selected = realtime_scored[:limit]
            
            logger.info(f"[Universe] 완료: 우상향 {len(scored)}종목 → 당일 주도주 상위 {len(selected)}종목 선정")
            for i, (code, name, mom, amt, today_chg) in enumerate(selected, 1):
                logger.info(
                    f"  {i:>2}. [{code}] {name:<20} "
                    f"당일상승 {today_chg:>+6.2f}% (20일수익 {mom*100:>+6.2f}%)"
                )
            return {code: name for code, name, _, _, _ in selected}
            
        else:
            scored.sort(key=lambda x: x[2], reverse=True)
            selected = scored[:limit]

            logger.info(
                f"[Universe] 완료: 우상향 {len(scored)}종목 → 상위 {len(selected)}종목 선정"
            )
            for i, (code, name, mom, amt) in enumerate(selected, 1):
                logger.info(
                    f"  {i:>2}. [{code}] {name:<20} "
                    f"20일수익률 {mom*100:>+6.2f}%  거래대금추정 {amt/1e8:>6,.0f}억"
                )

            return {code: name for code, name, _, _ in selected}
