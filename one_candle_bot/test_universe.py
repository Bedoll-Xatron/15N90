import logging
from market.universe import UniverseScreener

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    screener = UniverseScreener()
    results = screener.screen(limit=8)
    print("\n최종 선정 유니버스 (8종목):")
    for code, name in results.items():
        print(f" - {name} ({code})")
