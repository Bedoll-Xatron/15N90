from datetime import date
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from market.holidays import KoreanHolidayCalendar

cal   = KoreanHolidayCalendar()
today = date.today()

print(f"=== {today.year}년 하반기 공휴일 ===")
for m in range(today.month, 13):
    names = cal.holiday_names(today.year, m)
    for d, name in sorted(names.items()):
        print(f"  {d}  {name}")

print()
is_td = cal.is_trading_day(today)
print(f"오늘({today}): {'영업일' if is_td else '휴장일'}")
print(f"최근 영업일: {cal.last_trading_day()}")
print(f"다음 영업일: {cal.next_trading_day()}")
