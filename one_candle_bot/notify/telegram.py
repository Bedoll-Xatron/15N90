"""텔레그램 알림 — 신호 발생 시 메시지 전송"""
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _token()   -> str: return os.getenv("TELEGRAM_BOT_TOKEN", "")
def _chat_id() -> str: return os.getenv("TELEGRAM_CHAT_ID",   "")


def _enabled() -> bool:
    return bool(_token() and _chat_id())


def send(text: str) -> bool:
    """메시지 전송. 텔레그램 미설정이면 False 반환."""
    if not _enabled():
        return False
    try:
        r = requests.post(
            _API_URL.format(token=_token()),
            json={"chat_id": _chat_id(), "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"텔레그램 전송 실패: {e}")
        return False


def send_signal(
    ticker: str,
    name: str,
    direction: str,
    pattern: str,
    entry: float,
    stop: float,
    tp: float,
    rr: float,
    candle_time: str,
) -> None:
    """신호 알림 전송 (콘솔 + 텔레그램)"""
    emoji = "📈" if direction == "LONG" else "📉"
    lines = [
        f"{emoji} <b>[원캔들 신호]</b>",
        f"종목: {name} ({ticker})",
        f"방향: {direction}  패턴: {pattern}",
        f"시각: {candle_time[:2]}:{candle_time[2:4]}",
        f"진입: {entry:>10,.0f}원",
        f"손절: {stop:>10,.0f}원",
        f"익절: {tp:>10,.0f}원",
        f"손익비: {rr:.1f}",
    ]
    msg = "\n".join(lines)

    # 콘솔
    print("\n" + "=" * 44)
    for line in lines:
        print(" ", line.replace("<b>", "").replace("</b>", ""))
    print("=" * 44)

    # 텔레그램
    if send(msg):
        logger.info("텔레그램 전송 완료")


def send_summary(date: str, total: int, signals: int) -> None:
    """일일 스캔 완료 요약"""
    msg = (
        f"✅ <b>원캔들 스캔 완료</b>\n"
        f"날짜: {date}\n"
        f"감시 종목: {total}개\n"
        f"신호 발생: {signals}건"
    )
    print(f"\n[스캔 완료] {date}  감시:{total}종목  신호:{signals}건")
    send(msg)


def send_mock_buy(strategy_id: str, ticker: str, name: str, direction: str, price: float, qty: int, cost: float) -> None:
    emoji = "🛒"
    lines = [
        f"{emoji} <b>[전략 {strategy_id} 진입]</b>",
        f"종목: {name} ({ticker})",
        f"방향: {direction}",
        f"단가: {price:>10,.0f}원",
        f"수량: {qty:>10,}주",
        f"총액: {cost:>10,.0f}원",
    ]
    msg = "\n".join(lines)
    send(msg)


def send_mock_sell(strategy_id: str, ticker: str, name: str, price: float, pnl: float, reason: str) -> None:
    emoji = "💰" if pnl > 0 else "💸"
    lines = [
        f"{emoji} <b>[전략 {strategy_id} 청산]</b>",
        f"종목: {name} ({ticker})",
        f"단가: {price:>10,.0f}원",
        f"손익: {pnl:>10,.0f}원",
        f"사유: {reason}",
    ]
    msg = "\n".join(lines)
    send(msg)


def send_daily_report(date: str, stats: dict) -> None:
    emoji = "📊"
    lines = [
        f"{emoji} <b>[전략별 일일 성과 비교]</b>",
        f"날짜: {date}",
        "-" * 20
    ]
    
    for s_id, s_data in stats.items():
        lines.extend([
            f"<b>[전략 {s_id}]</b>",
            f"잔여 시드: {s_data['balance']:>10,.0f}원",
            f"일일 손익: {s_data['pnl_today']:>10,.0f}원",
            f"당일 거래: {s_data['trades_count']}건",
            "-" * 20
        ])
        
    msg = "\n".join(lines)
    send(msg)

