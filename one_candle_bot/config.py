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
    min_avg_trade_amount: int = 50_000_000_000  # 500억 이상 (주도주 필터 강화)
    max_prev_change_pct: float = 10.0
    min_prev_change_pct: float = -10.0
    top_n_per_market: int = 100                 # 시장별 거래량 순위 상위 N개 후보


@dataclass
class StrategyConfig:
    atr_period: int = 14
    atr_ratio: float = 0.20          # 0.33 -> 0.20 (박스 크기 조건 유지)
    box_vol_ratio: float = 0.20      # 첫 15분 박스 거래량이 20일 일평균 거래량의 20% 이상 터져야 함
    max_gap_pct: float = 5.0         # 장 시작 시초가 갭 상승 제한 (5% 초과 시 패스)
    target_rr: float = 2.0           # 기본 부분 익절 손익비
    pullback_volume_ratio: float = 0.5 # 눌림목 하락 시 거래량이 절반 이하로 말라야 함
    hammer_tail_ratio: float = 0.50  # 꼬리 비율 유지
    hammer_body_ratio: float = 0.35  # 몸통 비율 유지
    market_filter_pct: float = 1.5   # 코스피/코스닥 방향성 제한 유지
    crash_alpha_min_pct: float = 3.0 # 폭락장(-1.5% 이하) 예외 매수 허용 최소 상승률 (기본 3%)


UNIVERSE = UniverseConfig()
STRATEGY = StrategyConfig()
