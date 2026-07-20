import logging
from config import load_kis_config
from market.api_client import KISClient

logging.basicConfig(level=logging.INFO)

cfg = load_kis_config()
client = KISClient(cfg)

ranking = client.get_volume_ranking("Q", 2)
print("Keys:", ranking[0].keys() if ranking else "No data")
print("First item:", ranking[0] if ranking else "No data")
