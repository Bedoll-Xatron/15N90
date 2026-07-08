import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass(frozen=True)
class KISConfig:
    app_key: str
    app_secret: str
    base_url: str


def _require(key: str) -> str:
    val = os.getenv(key, "")
    if not val or val.startswith("여기에"):
        raise EnvironmentError(f"'{key}' 가 .env에 설정되지 않았습니다.")
    return val


def load_kis_config() -> KISConfig:
    return KISConfig(
        app_key=_require("KIS_APP_KEY"),
        app_secret=_require("KIS_APP_SECRET"),
        base_url=os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443"),
    )


@dataclass(frozen=True)
class UniverseConfig:
    min_market_cap: int = 100_000_000_000       # 1,000억 이상
    min_avg_trade_amount: int = 5_000_000_000   # 50억 이상
    max_prev_change_pct: float = 10.0
    min_prev_change_pct: float = -10.0
    top_n_per_market: int = 100                 # 시장별 거래량 순위 상위 N개 후보


@dataclass(frozen=True)
class StrategyConfig:
    atr_period: int = 14
    atr_ratio: float = 0.33          # 15분봉 크기 >= ATR * atr_ratio
    volume_multiplier: float = 1.5   # 15분봉 거래량 >= 일평균 * multiplier
    hammer_tail_ratio: float = 0.60  # 꼬리 >= 전체 범위 * 비율
    hammer_body_ratio: float = 0.25  # 몸통 <= 전체 범위 * 비율
    market_filter_pct: float = 1.0   # KOSPI/KOSDAQ ±1% 기준


UNIVERSE = UniverseConfig()
STRATEGY = StrategyConfig()
