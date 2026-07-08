# 분봉 CSV 데이터 준비 가이드

## 파일 위치 규칙
```
backtest/data/
└── {종목코드}/
    ├── {종목코드}_{YYYYMMDD}.csv   ← 하루치 1분봉
    └── ...
```

## CSV 형식 (1분봉)
```
time,open,high,low,close,volume
090100,60000,60200,59800,60100,15000
090200,60100,60300,59900,60200,12000
...
103000,60500,60700,60400,60600,8000
```
- `time`   : HHMMSS (24시 기준, 6자리)
- 가격     : 정수(원)
- 수집 구간: 09:00~10:30 (전략 범위) 또는 09:00~15:30 (전체)

## 데이터 준비 방법

### 방법 1 — KIS OpenAPI (tools/download_minute_csv.py)
.env 에 API 키 입력 후 실행:
```
python tools/download_minute_csv.py --ticker 005930 --start 20240101 --end 20241231
```
주의: KIS API는 당일 분봉만 제공합니다.
      이력 분봉이 필요하면 방법 2 또는 3을 사용하세요.

### 방법 2 — 키움증권 HTS 수동 내보내기
1. 영웅문4 → [0141] 주식분봉차트
2. 종목 입력, 기간 설정, 1분 선택
3. 우클릭 → Excel 내보내기
4. 변환: python tools/convert_hts_csv.py --src 내보낸파일.xls --ticker 005930

### 방법 3 — 다른 증권사 HTS
tools/convert_hts_csv.py 의 --fmt 옵션 참고
지원 형식: kiwoom(기본), ebest, samsung, nh
