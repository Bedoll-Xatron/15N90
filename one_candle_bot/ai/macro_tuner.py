import json
import logging
from ai.analyzer import NIMAnalyzer

logger = logging.getLogger(__name__)

def tune_daily_parameters(kospi_history: list[float], kosdaq_history: list[float]) -> dict:
    """
    최근 5일간의 코스피, 코스닥 종가 흐름을 바탕으로 AI에게 오늘의 최적 파라미터(box_vol_ratio 등)를 추천받습니다.
    """
    analyzer = NIMAnalyzer()
    if not analyzer.is_available():
        return {}

    kospi_str = ", ".join([f"{v:.2f}" for v in kospi_history])
    kosdaq_str = ", ".join([f"{v:.2f}" for v in kosdaq_history])

    prompt = f"""
당신은 퀀트 시스템 트레이딩의 위험 관리자입니다. 
아래는 최근 5일간의 한국 증시(코스피, 코스닥) 종가 추이입니다.
코스피 5일 흐름: [{kospi_str}]
코스닥 5일 흐름: [{kosdaq_str}]

이 데이터를 보고 오늘의 시장 추세(상승장, 하락장, 횡보장)를 판단한 뒤,
초단타(주도주 매매) 봇을 위한 다음 두 가지 파라미터의 권장 값을 제안해주세요.

1. box_vol_ratio: 아침 첫 15분 거래량 폭발 기준치 (보통 0.20, 하락장일 경우 보수적으로 0.25~0.30으로 올려 엄격히 필터링, 불장일 경우 0.15로 완화)
2. target_rr: 목표 손익비 (보통 2.0, 변동성이 크거나 하락장이면 1.5로 짧게 익절, 강세장이면 2.5~3.0으로 길게)

결과는 반드시 아래의 JSON 형식으로만 응답하세요.
{{
    "box_vol_ratio": 0.20,
    "target_rr": 2.0,
    "reason": "현재 시장은 ~하기 때문에 이 값을 추천합니다."
}}
"""
    try:
        content = analyzer._call_api_with_fallback(
            prompt=prompt,
            system_msg="You are a quant risk manager. Always reply with strict JSON.",
            temperature=0.1,
            max_tokens=150
        )
        if content.startswith("```json"): content = content[7:-3].strip()
        elif content.startswith("```"): content = content[3:-3].strip()
            
        result = json.loads(content)
        
        # 안전한 바운드 체크
        box_vol_ratio = max(0.1, min(0.5, float(result.get("box_vol_ratio", 0.20))))
        target_rr = max(1.0, min(3.0, float(result.get("target_rr", 2.0))))
        reason = result.get("reason", "")
        
        logger.info(f"[AI 매크로 튜닝] box_vol_ratio: {box_vol_ratio}, target_rr: {target_rr} (이유: {reason})")
        return {"box_vol_ratio": box_vol_ratio, "target_rr": target_rr}
        
    except Exception as e:
        logger.error(f"매크로 파라미터 튜닝 중 오류: {e}")
        return {}
