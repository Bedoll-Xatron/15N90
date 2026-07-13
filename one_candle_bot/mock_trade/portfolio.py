import json
import csv
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)

# 수수료 및 세금 (현실적 가정)
FEE_BUY = 0.00015
FEE_SELL = 0.00015
TAX = 0.0020
SLIPPAGE = 0.0005

@dataclass
class Position:
    ticker: str
    name: str
    direction: str  # 'LONG' or 'SHORT'
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    entry_time: str
    partial_sold: bool = False

    def current_value(self, current_price: float) -> float:
        if self.direction == 'LONG':
            return current_price * self.quantity
        else:
            return (self.entry_price + (self.entry_price - current_price)) * self.quantity

    def pnl(self, current_price: float) -> float:
        val = self.current_value(current_price)
        cost = self.entry_price * self.quantity
        gross_pnl = val - cost if self.direction == 'LONG' else cost - (current_price * self.quantity)
        
        # 비용 계산
        buy_fee = cost * (FEE_BUY + SLIPPAGE)
        sell_fee = (current_price * self.quantity) * (FEE_SELL + TAX + SLIPPAGE)
        
        return gross_pnl - buy_fee - sell_fee

class Portfolio:
    def __init__(self, strategy_id: str, data_dir: str = "mock_data"):
        self.strategy_id = strategy_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.portfolio_file = self.data_dir / f"portfolio_{strategy_id}.json"
        self.history_file = self.data_dir / f"trade_history_{strategy_id}.csv"
        
        self.balance: float = 10_000_000.0
        self.positions: dict[str, Position] = {} # ticker -> Position
        self.load()

    def load(self):
        if self.portfolio_file.exists():
            try:
                with open(self.portfolio_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.balance = data.get("balance", 10_000_000.0)
                    positions = data.get("positions", {})
                    for t, p_data in positions.items():
                        self.positions[t] = Position(**p_data)
            except Exception as e:
                logger.error(f"포트폴리오 로드 실패: {e}")

    def save(self):
        try:
            data = {
                "balance": self.balance,
                "positions": {t: asdict(p) for t, p in self.positions.items()}
            }
            with open(self.portfolio_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"포트폴리오 저장 실패: {e}")

    def buy(self, ticker: str, name: str, direction: str, price: float, quantity: int, stop_loss: float, take_profit: float):
        if ticker in self.positions:
            logger.warning(f"[{ticker}] 이미 포지션 보유 중입니다.")
            return False
            
        cost = price * quantity
        if cost > self.balance:
            logger.warning(f"[{ticker}] 잔고 부족: 필요 {cost:,.0f} > 잔고 {self.balance:,.0f}")
            return False

        # 잔고 차감 및 포지션 추가 (매수 비용 반영)
        buy_fee = cost * (FEE_BUY + SLIPPAGE)
        self.balance -= (cost + buy_fee)
        
        pos = Position(
            ticker=ticker,
            name=name,
            direction=direction,
            entry_price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self.positions[ticker] = pos
        self.save()
        logger.info(f"가상 매수: {name}({ticker}) {direction} {quantity}주 @ {price:,.0f} (비용: {buy_fee:,.0f})")
        return True

    def sell(self, ticker: str, current_price: float, reason: str = "Exit", sell_qty: int = 0):
        if ticker not in self.positions:
            return None
            
        pos = self.positions[ticker]
        if sell_qty <= 0 or sell_qty >= pos.quantity:
            # 전량 매도
            sell_qty = pos.quantity
            is_partial = False
        else:
            is_partial = True

        # PnL 계산 (부분 수량에 대해서만)
        val = current_price * sell_qty if pos.direction == 'LONG' else (pos.entry_price + (pos.entry_price - current_price)) * sell_qty
        cost = pos.entry_price * sell_qty
        gross_pnl = val - cost if pos.direction == 'LONG' else cost - (current_price * sell_qty)
        
        buy_fee = cost * (FEE_BUY + SLIPPAGE)
        sell_fee = (current_price * sell_qty) * (FEE_SELL + TAX + SLIPPAGE)
        
        net_pnl = gross_pnl - buy_fee - sell_fee
        
        # 반환금 = (원금 + 수수료) + PnL (간이 계산)
        self.balance += (cost + buy_fee) + net_pnl
            
        if is_partial:
            pos.quantity -= sell_qty
            pos.partial_sold = True
            self.save()
            self._record_history_partial(pos, sell_qty, current_price, net_pnl, reason)
            logger.info(f"부분 가상 매도: {pos.name}({ticker}) {sell_qty}주 @ {current_price:,.0f} | 손익: {net_pnl:,.0f} ({reason})")
        else:
            del self.positions[ticker]
            self.save()
            self._record_history_partial(pos, sell_qty, current_price, net_pnl, reason)
            logger.info(f"가상 매도: {pos.name}({ticker}) @ {current_price:,.0f} | 손익: {net_pnl:,.0f} ({reason})")
            
        return net_pnl

    def _record_history_partial(self, pos: Position, sell_qty: int, exit_price: float, pnl: float, reason: str):
        write_header = not self.history_file.exists()
        try:
            with open(self.history_file, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["entry_time", "exit_time", "ticker", "name", "direction", "quantity", "entry_price", "exit_price", "pnl", "reason"])
                
                writer.writerow([
                    pos.entry_time,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    pos.ticker,
                    pos.name,
                    pos.direction,
                    sell_qty,
                    pos.entry_price,
                    exit_price,
                    f"{pnl:.0f}",
                    reason
                ])
        except Exception as e:
            logger.error(f"거래 기록 실패: {e}")
