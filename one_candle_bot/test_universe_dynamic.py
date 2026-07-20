import logging
from config import load_kis_config
from market.api_client import KISClient
from market.universe import UniverseScreener

logging.basicConfig(level=logging.INFO)

cfg = load_kis_config()
client = KISClient(cfg)

screener = UniverseScreener()

print("Testing dynamic universe screening (pykrx -> KIS API -> MAJOR_TICKERS)")
try:
    results = screener.screen(limit=5, client=client)
    print("\n[Final Selected Universe]")
    for i, (code, name) in enumerate(results.items()):
        print(f"{i+1}. {code}: {name}")
except Exception as e:
    print("Error:", e)
