"""
1단계 검증 스크립트
실행: python verify_step1.py

API 키가 설정된 경우 실제 KIS API 연동을 테스트합니다.
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def check_env() -> bool:
    """환경변수 및 .env 파일 확인"""
    print("\n" + "=" * 50)
    print("[ 1 ] 환경변수 확인")
    print("=" * 50)
    try:
        from config import load_kis_config, load_telegram_config, RISK, UNIVERSE, STRATEGY
        kis = load_kis_config()
        tg = load_telegram_config()
        print(f"  KIS Base URL  : {kis.base_url}")
        print(f"  모의투자 여부 : {kis.is_paper}")
        print(f"  계좌번호      : {kis.cano[:4]}****")
        print(f"  텔레그램 봇   : {tg.bot_token[:10]}...")
        print(f"  일일 손실한도 : {RISK.max_daily_loss_pct * 100:.0f}%")
        print(f"  거래 시간     : {RISK.trading_start} ~ {RISK.trading_end}")
        print(f"  ATR 비율      : {STRATEGY.atr_ratio}")
        print(f"  최소 시총     : {UNIVERSE.min_market_cap / 1e8:.0f}억")
        print("  → OK")
        return True
    except EnvironmentError as exc:
        print(f"  → FAIL: {exc}")
        return False


def check_token() -> bool:
    """KIS API 토큰 발급 테스트"""
    print("\n" + "=" * 50)
    print("[ 2 ] KIS API 토큰 발급")
    print("=" * 50)
    try:
        from config import load_kis_config
        from market.api_client import KISClient
        client = KISClient(load_kis_config())
        token = client._ensure_token()
        print(f"  토큰 앞 20자: {token[:20]}...")
        print(f"  만료 시각   : {client._token_expires_at}")
        print("  → OK")
        return True, client  # type: ignore[return-value]
    except Exception as exc:
        print(f"  → FAIL: {exc}")
        return False, None  # type: ignore[return-value]


def check_stock_price(client) -> bool:
    """삼성전자 현재가 조회 테스트"""
    print("\n" + "=" * 50)
    print("[ 3 ] 주식 현재가 조회 (삼성전자 005930)")
    print("=" * 50)
    try:
        price_info = client.get_stock_price("005930")
        print(f"  종목명   : {price_info.get('hts_kor_isnm', 'N/A')}")
        print(f"  현재가   : {int(price_info.get('stck_prpr', 0)):,}원")
        print(f"  시가총액 : {price_info.get('hts_avls', 'N/A')}억")
        print(f"  전일대비 : {price_info.get('prdy_ctrt', 'N/A')}%")
        print("  → OK")
        return True
    except Exception as exc:
        print(f"  → FAIL: {exc}")
        return False


def check_daily_ohlcv(client) -> bool:
    """일봉 데이터 조회 테스트"""
    print("\n" + "=" * 50)
    print("[ 4 ] 일봉 데이터 조회 (삼성전자, 최근 5일)")
    print("=" * 50)
    try:
        ohlcv = client.get_daily_ohlcv("005930", count=5)
        if not ohlcv:
            print("  → FAIL: 데이터 없음")
            return False
        for row in ohlcv:
            print(
                f"  {row.get('stck_bsop_date', '?')} | "
                f"시 {int(row.get('stck_oprc', 0)):>8,} "
                f"고 {int(row.get('stck_hgpr', 0)):>8,} "
                f"저 {int(row.get('stck_lwpr', 0)):>8,} "
                f"종 {int(row.get('stck_clpr', 0)):>8,}"
            )
        print("  → OK")
        return True
    except Exception as exc:
        print(f"  → FAIL: {exc}")
        return False


def check_universe(client) -> bool:
    """유니버스 스크리닝 테스트"""
    print("\n" + "=" * 50)
    print("[ 5 ] 유니버스 스크리닝")
    print("=" * 50)
    try:
        from market.universe import UniverseScreener
        screener = UniverseScreener(client)
        codes = screener.screen()
        print(f"\n  → 선정 종목 수: {len(codes)}개")
        print(f"  → 종목 코드: {codes[:10]}{'...' if len(codes) > 10 else ''}")
        print("  → OK")
        return True
    except Exception as exc:
        print(f"  → FAIL: {exc}")
        return False


def check_market_index(client) -> bool:
    """시장 지수 조회 테스트"""
    print("\n" + "=" * 50)
    print("[ 6 ] 시장 지수 조회 (KOSPI / KOSDAQ)")
    print("=" * 50)
    try:
        kospi = client.get_market_index("0001")
        kosdaq = client.get_market_index("1001")
        print(
            f"  KOSPI  : {float(kospi.get('bstp_nmix_prpr', 0)):,.2f}  "
            f"({kospi.get('bstp_nmix_prdy_ctrt', 'N/A')}%)"
        )
        print(
            f"  KOSDAQ : {float(kosdaq.get('bstp_nmix_prpr', 0)):,.2f}  "
            f"({kosdaq.get('bstp_nmix_prdy_ctrt', 'N/A')}%)"
        )
        print("  → OK")
        return True
    except Exception as exc:
        print(f"  → FAIL: {exc}")
        return False


def main() -> None:
    print("\n" + "=" * 50)
    print("  원캔들 봇 - 1단계 검증")
    print("=" * 50)

    env_ok = check_env()
    if not env_ok:
        print("\n.env 파일에 API 키를 먼저 입력하세요.")
        sys.exit(1)

    token_ok, client = check_token()
    if not token_ok:
        print("\nKIS API 키를 확인하세요 (앱키/시크릿 오류 또는 네트워크 문제).")
        sys.exit(1)

    results = {
        "현재가 조회": check_stock_price(client),
        "일봉 조회": check_daily_ohlcv(client),
        "시장 지수": check_market_index(client),
        "유니버스 스크리닝": check_universe(client),
    }

    print("\n" + "=" * 50)
    print("[ 최종 결과 ]")
    print("=" * 50)
    all_pass = True
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {name:<20} {status}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  모든 항목 통과 → 2단계 진행 가능")
    else:
        print("  일부 항목 실패 → 위 오류 메시지를 확인하세요")
    print()


if __name__ == "__main__":
    main()
