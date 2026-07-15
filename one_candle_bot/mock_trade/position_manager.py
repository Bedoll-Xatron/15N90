import logging
from typing import Callable

from .portfolio import Portfolio
from market.api_client import KISClient

logger = logging.getLogger(__name__)

class PositionManager:
    def __init__(self, portfolio: Portfolio, client: KISClient, on_sell_callback: Callable = None):
        self.portfolio = portfolio
        self.client = client
        self.on_sell_callback = on_sell_callback

    def check_positions(self):
        """보유 중인 포지션의 현재가를 확인하고 익절/손절 조건에 도달했는지 검사합니다."""
        tickers = list(self.portfolio.positions.keys())
        if not tickers:
            return

        for ticker in tickers:
            pos = self.portfolio.positions[ticker]
            try:
                price_info = self.client.get_stock_price(ticker)
                current_price_str = price_info.get("stck_prpr", "0")
                current_price = float(current_price_str)
                if current_price <= 0:
                    continue
                    
                reason = None
                is_partial = False
                
                from config import STRATEGY
                target_rr = getattr(STRATEGY, 'target_rr', 2.0)
                
                # 최고가 갱신 로직 추가
                if current_price > pos.highest_price:
                    pos.highest_price = current_price
                    self.portfolio.save() # 상태 저장
                
                if pos.direction == 'LONG':
                    rr2_price = pos.entry_price + (pos.entry_price - pos.stop_loss) * target_rr
                    
                    # 진성 트레일링 스탑: 현재 설정된 손절폭
                    risk_amount = pos.entry_price - pos.stop_loss
                    dynamic_stop_loss = max(pos.stop_loss, pos.highest_price - risk_amount * 1.5) # 최고점에서 리스크의 1.5배 하락 시 컷
                    
                    if current_price <= dynamic_stop_loss:
                        reason = f"트레일링 스탑 (최고가 {pos.highest_price:,.0f} 대비 하락)"
                        if dynamic_stop_loss == pos.stop_loss:
                            reason = "손절 (Stop Loss)"
                        # 최종 익절과 동일하게 전량 매도
                        
                    elif not pos.partial_sold and current_price >= rr2_price:
                        reason = f"부분 익절 (RR {target_rr} 도달)"
                        is_partial = True
                    elif current_price >= pos.take_profit:
                        reason = "최종 익절 (Take Profit)"
                else: # SHORT
                    rr2_price = pos.entry_price - (pos.stop_loss - pos.entry_price) * target_rr
                    
                    if current_price >= pos.stop_loss:
                        reason = "손절 (Stop Loss)"
                    elif not pos.partial_sold and current_price <= rr2_price:
                        reason = f"부분 익절 (RR {target_rr} 도달)"
                        is_partial = True
                    elif current_price <= pos.take_profit:
                        reason = "최종 익절 (Take Profit)"
                        
                if reason:
                    if is_partial:
                        sell_qty = pos.quantity // 2
                        if sell_qty > 0:
                            pnl = self.portfolio.sell(ticker, current_price, reason, sell_qty=sell_qty)
                            if self.on_sell_callback and pnl is not None:
                                self.on_sell_callback(pos, current_price, pnl, reason)
                            # 본절 컷 상향/하향
                            pos.stop_loss = pos.entry_price
                            self.portfolio.save()
                    else:
                        pnl = self.portfolio.sell(ticker, current_price, reason)
                        if self.on_sell_callback and pnl is not None:
                            self.on_sell_callback(pos, current_price, pnl, reason)

            except Exception as e:
                logger.error(f"[{ticker}] 포지션 가격 확인 실패: {e}")

    def force_close_all(self, reason: str = "장 마감 (Time Exit)"):
        """모든 포지션을 현재가로 강제 청산합니다."""
        tickers = list(self.portfolio.positions.keys())
        for ticker in tickers:
            pos = self.portfolio.positions[ticker]
            try:
                price_info = self.client.get_stock_price(ticker)
                current_price_str = price_info.get("stck_prpr", "0")
                current_price = float(current_price_str)
                if current_price > 0:
                    pnl = self.portfolio.sell(ticker, current_price, reason)
                    if self.on_sell_callback and pnl is not None:
                        self.on_sell_callback(pos, current_price, pnl, reason)
            except Exception as e:
                logger.error(f"[{ticker}] 포지션 강제 청산 실패: {e}")
