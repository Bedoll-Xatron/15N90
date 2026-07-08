"""
HTS 분봉 내보내기 파일 → 표준 CSV 변환기

지원 형식:
  kiwoom  : 키움증권 영웅문4 [0141] 분봉 Excel 내보내기
  ebest   : 이베스트증권 xingAPI / HTS 내보내기
  samsung : 삼성증권 POP 분봉 내보내기
  nh      : NH투자증권 QV 분봉 내보내기

사용법:
  python tools/convert_hts_csv.py --src 파일경로 --ticker 005930 --fmt kiwoom
  python tools/convert_hts_csv.py --src 파일경로 --ticker 005930 --fmt kiwoom --date 20240103
"""
import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "backtest" / "data"

# ------------------------------------------------------------------ #
#  각 증권사 컬럼 매핑                                                 #
# ------------------------------------------------------------------ #

_FORMATS = {
    "kiwoom": {
        # 영웅문4 분봉 내보내기 (기본 컬럼명)
        "date":   "날짜",
        "time":   "시간",
        "open":   "시가",
        "high":   "고가",
        "low":    "저가",
        "close":  "현재가",  # 또는 "종가"
        "volume": "거래량",
        "encoding": "cp949",
        "skiprows": 0,
    },
    "ebest": {
        "date":   "일자",
        "time":   "시각",
        "open":   "시가",
        "high":   "고가",
        "low":    "저가",
        "close":  "종가",
        "volume": "거래량",
        "encoding": "cp949",
        "skiprows": 1,
    },
    "samsung": {
        "date":   "날짜",
        "time":   "시간",
        "open":   "시가",
        "high":   "고가",
        "low":    "저가",
        "close":  "종가",
        "volume": "거래량",
        "encoding": "utf-8-sig",
        "skiprows": 0,
    },
    "nh": {
        "date":   "일자",
        "time":   "시간",
        "open":   "시가",
        "high":   "고가",
        "low":    "저가",
        "close":  "종가",
        "volume": "거래량",
        "encoding": "cp949",
        "skiprows": 0,
    },
}


# ------------------------------------------------------------------ #
#  변환 로직                                                           #
# ------------------------------------------------------------------ #

def _normalize_time(t: str) -> str:
    """다양한 시간 포맷 → HHMMSS 변환"""
    t = str(t).strip().replace(":", "").replace(" ", "")
    # HH:MM → HHMMSS 추가
    if len(t) == 4:
        return t + "00"
    if len(t) == 6:
        return t
    # HH:MM:SS → HHMMSS (already stripped colons)
    return t[:6]


def _normalize_date(d) -> str:
    """날짜 → YYYYMMDD"""
    s = str(d).replace("-", "").replace("/", "").strip()
    return s[:8]


def convert(src: Path, ticker: str, fmt: str, force_date: str | None = None) -> list[Path]:
    """
    HTS 파일 → 표준 CSV 변환.
    반환: 저장된 파일 경로 리스트
    """
    if fmt not in _FORMATS:
        raise ValueError(f"지원하지 않는 형식: {fmt}. 지원: {list(_FORMATS.keys())}")

    spec = _FORMATS[fmt]
    enc  = spec["encoding"]
    skip = spec["skiprows"]

    # 파일 읽기 (xlsx / xls / csv 모두 지원)
    suffix = src.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(src, skiprows=skip)
    else:
        df = pd.read_csv(src, encoding=enc, skiprows=skip)

    # 컬럼 정규화
    df.columns = [str(c).strip() for c in df.columns]

    # 키움은 "현재가" 또는 "종가" 두 가지 가능
    close_col = spec["close"]
    if close_col not in df.columns and "종가" in df.columns:
        close_col = "종가"

    # 필요 컬럼만 추출
    sub = df[[spec["date"], spec["time"], spec["open"],
              spec["high"], spec["low"], close_col, spec["volume"]]].copy()
    sub.columns = ["date", "time", "open", "high", "low", "close", "volume"]

    # 타입 변환
    sub["date"]   = sub["date"].apply(_normalize_date)
    sub["time"]   = sub["time"].apply(_normalize_time)
    sub["open"]   = pd.to_numeric(sub["open"],   errors="coerce").fillna(0).astype(int)
    sub["high"]   = pd.to_numeric(sub["high"],   errors="coerce").fillna(0).astype(int)
    sub["low"]    = pd.to_numeric(sub["low"],    errors="coerce").fillna(0).astype(int)
    sub["close"]  = pd.to_numeric(sub["close"],  errors="coerce").fillna(0).astype(int)
    sub["volume"] = pd.to_numeric(sub["volume"], errors="coerce").fillna(0).astype(int)

    # 09:00 이전 제거 (프리마켓 노이즈)
    sub = sub[sub["time"] >= "090000"]

    # force_date 옵션
    if force_date:
        sub["date"] = force_date

    saved: list[Path] = []
    for trade_date, group in sub.groupby("date"):
        out_dir = DATA_DIR / ticker
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ticker}_{trade_date}.csv"

        rows = group.sort_values("time")[["time", "open", "high", "low", "close", "volume"]]
        rows.to_csv(out_path, index=False)
        print(f"  저장: {out_path}  ({len(rows)}행)")
        saved.append(out_path)

    return saved


# ------------------------------------------------------------------ #
#  진입점                                                              #
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="HTS 분봉 내보내기 → 표준 CSV 변환")
    parser.add_argument("--src",    required=True, help="HTS 내보내기 파일 경로")
    parser.add_argument("--ticker", required=True, help="종목코드 (예: 005930)")
    parser.add_argument("--fmt",    default="kiwoom",
                        choices=list(_FORMATS.keys()), help="증권사 형식")
    parser.add_argument("--date",   default=None,
                        help="날짜 강제 지정 YYYYMMDD (단일 날짜 파일인 경우)")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {src}")
        sys.exit(1)

    print(f"변환 중: {src} → {args.ticker} ({args.fmt})")
    saved = convert(src, args.ticker, args.fmt, args.date)
    print(f"\n완료: {len(saved)}개 파일 저장됨")
    print(f"위치: backtest/data/{args.ticker}/")


if __name__ == "__main__":
    main()
