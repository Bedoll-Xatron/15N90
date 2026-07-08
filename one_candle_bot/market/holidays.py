"""
한국 공휴일 조회 모듈

data.go.kr 한국천문연구원_특일정보 API 사용.
임시공휴일·선거일·대체공휴일 포함.
"""
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

_API_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
_TIMEOUT = 10


class KoreanHolidayCalendar:
    """
    한국 공휴일 캘린더

    is_trading_day(d) : 영업일(주말·공휴일 제외) 여부
    last_trading_day() : 가장 최근 영업일
    next_trading_day() : 다음 영업일
    """

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.getenv("HOLIDAY_API_KEY", "")
        self._cache: dict[str, set[str]] = {}   # {"YYYYMM": {"YYYYMMDD", ...}}

    # ------------------------------------------------------------------ #
    #  공개 메서드                                                         #
    # ------------------------------------------------------------------ #

    def is_holiday(self, d: date) -> bool:
        """공휴일(주말 포함) 여부"""
        if d.weekday() >= 5:          # 토=5, 일=6
            return True
        return d.strftime("%Y%m%d") in self._holidays(d.year, d.month)

    def is_trading_day(self, d: date) -> bool:
        return not self.is_holiday(d)

    def last_trading_day(self, from_date: date | None = None) -> date:
        """from_date 기준 가장 최근 영업일 (당일 포함)"""
        d = from_date or date.today()
        while self.is_holiday(d):
            d -= timedelta(days=1)
        return d

    def next_trading_day(self, from_date: date | None = None) -> date:
        """from_date 기준 다음 영업일 (당일 제외)"""
        d = (from_date or date.today()) + timedelta(days=1)
        while self.is_holiday(d):
            d += timedelta(days=1)
        return d

    def holiday_names(self, year: int, month: int) -> dict[str, str]:
        """해당 월의 공휴일 {YYYYMMDD: 이름}"""
        return self._holiday_names(year, month)

    # ------------------------------------------------------------------ #
    #  내부 — API 호출 및 캐시                                            #
    # ------------------------------------------------------------------ #

    def _holidays(self, year: int, month: int) -> set[str]:
        key = f"{year}{month:02d}"
        if key not in self._cache:
            self._cache[key] = set(self._holiday_names(year, month).keys())
        return self._cache[key]

    def _holiday_names(self, year: int, month: int) -> dict[str, str]:
        if not self._api_key:
            logger.warning("HOLIDAY_API_KEY 미설정 — 주말만 휴장 처리")
            return {}

        try:
            resp = requests.get(
                _API_URL,
                params={
                    "serviceKey": self._api_key,
                    "solYear":    str(year),
                    "solMonth":   f"{month:02d}",
                    "_type":      "json",
                    "numOfRows":  50,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()["response"]["body"]
            total = body.get("totalCount", 0)
            if total == 0:
                return {}

            items = body["items"]["item"]
            # 단건이면 dict, 복수면 list
            if isinstance(items, dict):
                items = [items]

            return {
                str(item["locdate"]): item["dateName"]
                for item in items
                if item.get("isHoliday") == "Y"
            }

        except Exception as e:
            logger.warning(f"공휴일 API 조회 실패 ({year}-{month:02d}): {e}")
            return {}


# ------------------------------------------------------------------ #
#  모듈 레벨 싱글턴                                                    #
# ------------------------------------------------------------------ #

_calendar: KoreanHolidayCalendar | None = None


def get_calendar() -> KoreanHolidayCalendar:
    global _calendar
    if _calendar is None:
        _calendar = KoreanHolidayCalendar()
    return _calendar
