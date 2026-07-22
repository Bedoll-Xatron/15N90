import logging
from config import load_kis_config
from market.api_client import KISClient

logging.basicConfig(level=logging.INFO)

cfg = load_kis_config()
client = KISClient(cfg)

ranking = client.get_minute_ohlcv("475150", "091720")
print("Minute OHLCV:", ranking[:2] if ranking else "No data")
