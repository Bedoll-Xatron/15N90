"""텔레그램 연결 테스트"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print(f"TOKEN  : {TOKEN[:20]}...")
print(f"CHAT_ID: {CHAT_ID}")

# 1) 봇 정보 확인
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
bot = r.json()
if bot.get("ok"):
    info = bot["result"]
    print(f"\n봇 이름: {info['first_name']} (@{info.get('username','?')})")
else:
    print(f"\n봇 조회 실패: {bot}")
    sys.exit(1)

# 2) 테스트 메시지 전송
msg = (
    "✅ <b>원캔들 스캐너 연결 테스트</b>\n"
    "텔레그램 알림이 정상 설정되었습니다.\n"
    "신호 발생 시 이 채팅으로 알림이 옵니다."
)
r2 = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
    timeout=10,
)
result = r2.json()
if result.get("ok"):
    print("메시지 전송 성공!")
else:
    print(f"전송 실패: {result.get('description', result)}")
    # CHAT_ID가 잘못됐을 가능성 → getUpdates로 실제 ID 확인
    print("\n실제 Chat ID 확인 시도...")
    r3 = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=10)
    updates = r3.json()
    if updates.get("result"):
        for upd in updates["result"][-3:]:
            chat = upd.get("message", {}).get("chat", {})
            print(f"  chat_id={chat.get('id')}  type={chat.get('type')}  name={chat.get('first_name','')}")
    else:
        print("  업데이트 없음 — 봇에게 먼저 /start 메시지를 보내세요")
