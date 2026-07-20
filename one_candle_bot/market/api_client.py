import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from config import KISConfig

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = Path(__file__).parent.parent / ".token_cache.json"
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3


class KISAPIError(Exception):
    pass


class KISClient:
    def __init__(self, cfg: KISConfig):
        self._cfg = cfg
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._load_cached_token()

    # ------------------------------------------------------------------ #
    #  토큰 관리                                                           #
    # ------------------------------------------------------------------ #

    def _load_cached_token(self) -> None:
        if not TOKEN_CACHE_FILE.exists():
            return
        try:
            data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.now() < expires_at - timedelta(minutes=30):
                self._access_token = data["access_token"]
                self._token_expires_at = expires_at
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    def _save_token_cache(self) -> None:
        TOKEN_CACHE_FILE.write_text(
            json.dumps({
                "access_token": self._access_token,
                "expires_at": self._token_expires_at.isoformat(),  # type: ignore[union-attr]
            }),
            encoding="utf-8",
        )

    def _ensure_token(self) -> str:
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at - timedelta(minutes=30):
                return self._access_token
        self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    def _refresh_token(self) -> None:
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"KIS 토큰 발급 중... (시도 {attempt}/{MAX_RETRIES})")
                resp = requests.post(
                    f"{self._cfg.base_url}/oauth2/tokenP",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self._cfg.app_key,
                        "appsecret": self._cfg.app_secret,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                self._access_token = data["access_token"]
                self._token_expires_at = datetime.now() + timedelta(seconds=int(data["expires_in"]))
                self._save_token_cache()
                logger.info(f"토큰 발급 완료 (만료: {self._token_expires_at:%Y-%m-%d %H:%M})")
                return
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(attempt * 2)  # 2초, 4초 대기
        
        raise RuntimeError(f"KIS 토큰 발급 실패: {last_exc}") from last_exc

    # ------------------------------------------------------------------ #
    #  공통 GET                                                            #
    # ------------------------------------------------------------------ #

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self._cfg.app_key,
            "appsecret": self._cfg.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        url = f"{self._cfg.base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self._headers(tr_id),
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("rt_cd") != "0":
                    raise KISAPIError(f"[{data.get('msg_cd')}] {data.get('msg1', '오류')}")
                return data
            except (requests.RequestException, KISAPIError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(attempt)

        raise RuntimeError(f"API 요청 실패 [{tr_id}]: {last_exc}") from last_exc

    # ------------------------------------------------------------------ #
    #  데이터 조회                                                         #
    # ------------------------------------------------------------------ #

    def get_stock_price(self, stock_code: str) -> dict:
        """현재가 시세 (시가총액 포함)"""
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code},
        )["output"]

    def get_daily_ohlcv(self, stock_code: str, count: int = 20) -> list[dict]:
        """일봉 OHLCV (최신순, count일)"""
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        return data.get("output2", [])[:count]

    def get_minute_ohlcv(self, stock_code: str, time_hhmmss: str = "103000") -> list[dict]:
        """분봉 OHLCV (지정 시각 기준 이전 데이터, 최신순)"""
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            tr_id="FHKST03010200",
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_HOUR_1": time_hhmmss,
                "FID_PW_DATA_INCU_YN": "N",
            },
        )
        return data.get("output2", [])

    def get_volume_ranking(self, market: str = "J", top_n: int = 100) -> list[dict]:
        """거래량 순위 (J: KOSPI, Q: KOSDAQ)"""
        iscd = "0001" if market == "J" else "1001"
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": iscd,
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        return data.get("output", [])[:top_n]

    def get_market_index(self, index_code: str = "0001") -> dict:
        """지수 조회 (0001: KOSPI, 1001: KOSDAQ)"""
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            tr_id="FHPUP02100000",
            params={"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": index_code},
        )["output"]
