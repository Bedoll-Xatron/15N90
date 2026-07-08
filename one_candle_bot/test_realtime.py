import logging
from config import load_kis_config
from market.api_client import KISClient
from market.universe import UniverseScreener

logging.basicConfig(level=logging.INFO)

def test_realtime_universe():
    print("실시간 유니버스 추출 테스트 시작 (KIS API 호출 포함)")
    cfg = load_kis_config()
    client = KISClient(cfg)
    
    screener = UniverseScreener()
    results = screener.screen(limit=8, client=client)
    
    print("\n최종 선정 주도주 유니버스 (8종목):")
    for code, name in results.items():
        print(f" - {name} ({code})")

if __name__ == "__main__":
    test_realtime_universe()
