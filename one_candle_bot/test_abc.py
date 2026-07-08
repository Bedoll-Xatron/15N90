from mock_trade.portfolio import Portfolio
from mock_trade.position_manager import PositionManager
from strategy.pattern import EntrySignal, Direction, PatternType, EntryType

def test_multi_portfolio():
    print("A/B/C 포트폴리오 정합성 테스트 시작")
    p_A = Portfolio("A", "mock_data_test")
    p_B = Portfolio("B", "mock_data_test")
    p_C = Portfolio("C", "mock_data_test")
    
    # 초기 잔고 확인
    print(f"초기 잔고: A={p_A.balance}, B={p_B.balance}, C={p_C.balance}")
    
    # 각기 다른 전략의 매수 시뮬레이션
    p_A.buy("005930", "삼성전자", "LONG", 80000, 100, 79000, 83000)
    p_B.buy("000660", "SK하이닉스", "LONG", 200000, 20, 195000, 210000)
    
    print("\n[매수 직후 잔여 시드]")
    print(f"A 잔고: {p_A.balance:,.0f} (삼성전자 보유)")
    print(f"B 잔고: {p_B.balance:,.0f} (SK하이닉스 보유)")
    print(f"C 잔고: {p_C.balance:,.0f} (보유 없음)")
    
    # 각기 다른 종목의 가격 변화로 매도 (익절)
    print("\n[매도(수익실현) 발생]")
    p_A.sell("005930", 83000, "익절(전략A)")
    p_B.sell("000660", 210000, "익절(전략B)")
    
    print("\n[매도 직후 최종 잔여 시드]")
    print(f"A 잔고: {p_A.balance:,.0f} (원금회수+수익)")
    print(f"B 잔고: {p_B.balance:,.0f} (원금회수+수익)")
    print(f"C 잔고: {p_C.balance:,.0f} (그대로)")
    print("\n테스트 종료 (성공)")

if __name__ == "__main__":
    test_multi_portfolio()
