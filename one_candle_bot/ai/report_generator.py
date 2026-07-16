import os
import csv
from datetime import datetime
import logging
from ai.analyzer import NIMAnalyzer

logger = logging.getLogger(__name__)

def generate_daily_report(history_csv: str, kospi_chg: float, kosdaq_chg: float) -> str:
    """
    당일 거래 내역(CSV)을 읽어 AI에게 전달하고, 
    오늘 장세 대비 봇의 성과 분석 및 내일 매매 전략에 대한 리뷰를 생성합니다.
    """
    if not os.path.exists(history_csv):
        return "오늘 발생한 거래 내역이 없습니다."

    # 당일 거래 내역 필터링
    today_str = datetime.now().strftime("%Y-%m-%d")
    trades = []
    
    with open(history_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["exit_time"].startswith(today_str):
                trades.append(row)

    if not trades:
        return "오늘 청산된 거래 내역이 없습니다."

    # 거래 요약 정보 만들기
    total_pnl = 0
    win_count = 0
    loss_count = 0
    trade_details = []

    for t in trades:
        pnl = float(t["pnl"])
        total_pnl += pnl
        if pnl > 0: win_count += 1
        elif pnl < 0: loss_count += 1
        
        trade_details.append(
            f"- 종목: {t['name']}({t['ticker']}), 방향: {t['direction']}, "
            f"사유: {t['reason']}, 손익: {pnl:,.0f}원"
        )

    trade_text = "\n".join(trade_details)
    summary_text = (
        f"총 거래 횟수: {len(trades)}회\n"
        f"승/패: {win_count}승 {loss_count}패\n"
        f"일간 총 손익: {total_pnl:,.0f}원\n"
        f"코스피 변동률: {kospi_chg:.2f}%\n"
        f"코스닥 변동률: {kosdaq_chg:.2f}%"
    )

    prompt = f"""
당신은 한국 주식시장에서 매우 냉철하고 전문적인 트레이딩 멘토입니다.
다음은 오늘 15N90 트레이딩 봇의 자동매매 결과입니다.

[오늘 시장 상황]
코스피 변동률: {kospi_chg:.2f}%
코스닥 변동률: {kosdaq_chg:.2f}%

[오늘 매매 요약]
{summary_text}

[상세 매매 내역]
{trade_text}

위 데이터를 바탕으로 다음 양식에 맞춰 짧고 명확한 데일리 리뷰를 작성해 주세요. (마크다운 사용, 존댓말)

1. **시장 대비 성과 평가** (오늘 지수 흐름 대비 봇이 방어를 잘했는지, 수익을 잘 냈는지 분석)
2. **손절 원인 및 칭찬** (수익이 났다면 어떤 점이 좋았는지, 손절이 발생했다면 시장 탓인지/휩소였는지 추정)
3. **내일의 대응 전략** (지수 상황을 고려해 내일은 보수적으로 할지 공격적으로 할지 한 줄 조언)
"""
    
    analyzer = NIMAnalyzer()
    if not analyzer.is_available():
        return "NVIDIA API KEY가 설정되지 않아 리포트를 생성할 수 없습니다.\n" + summary_text
        
    try:
        report = analyzer._call_api_with_fallback(
            prompt=prompt,
            system_msg="You are a professional trading analyst. Be concise and insightful.",
            temperature=0.3,
            max_tokens=500
        )
        return report
    except Exception as e:
        logger.error(f"리포트 생성 중 오류: {e}")
        return summary_text + "\n(AI 리포트 생성 실패)"
