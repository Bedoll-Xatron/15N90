from pathlib import Path
import shutil
import logging
from mock_trade.portfolio import Portfolio
from mock_trade.position_manager import PositionManager

logging.basicConfig(level=logging.INFO)

class MockClient:
    def __init__(self, prices):
        self.prices = prices
    
    def get_stock_price(self, ticker):
        return {"stck_prpr": str(self.prices.get(ticker, 0))}

def run_test():
    test_dir = Path("mock_data_test")
    if test_dir.exists():
        shutil.rmtree(test_dir)
        
    p = Portfolio(data_dir=str(test_dir))
    print(f"Initial balance: {p.balance:,.0f}")
    
    # Buy 100 shares of 005930 at 80,000 (Cost: 8,000,000 + fee)
    # Stop loss 79,000, Take profit 82,000
    success = p.buy("005930", "삼성전자", "LONG", 80000, 100, 79000, 82000)
    print(f"Buy success: {success}, Balance after buy: {p.balance:,.0f}")
    
    # Position Manager with Mock Client
    client = MockClient({"005930": 81000}) # Price didn't reach target
    def on_sell(pos, price, pnl, reason):
        print(f"Sold! {pos.name} @ {price}, PnL: {pnl:,.0f}, Reason: {reason}")
        
    pm = PositionManager(p, client, on_sell_callback=on_sell)
    
    print("Checking positions (price 81,000)...")
    pm.check_positions()
    print(f"Positions left: {list(p.positions.keys())}")
    
    print("Checking positions (price 83,000 - Take Profit!)...")
    client.prices["005930"] = 83000
    pm.check_positions()
    print(f"Positions left: {list(p.positions.keys())}, Balance: {p.balance:,.0f}")
    
    # Cleanup
    shutil.rmtree(test_dir)

if __name__ == "__main__":
    run_test()
