import os
import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

class NIMAnalyzer:
    def __init__(self):
        api_key = os.getenv("NVIDIA_API_KEY")
        self.model = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")
        
        if not api_key:
            logger.warning("NVIDIA_API_KEY가 설정되지 않아 AI 기능을 사용할 수 없습니다.")
            self.client = None
        else:
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key
            )

    def is_available(self) -> bool:
        return self.client is not None

    def analyze_news_catalyst(self, ticker: str, name: str, headlines: list[str]) -> bool:
        """
        뉴스 헤드라인을 분석하여 매매하기 적합한 호재인지 판별합니다.
        악재(유상증자, 배임, 블록딜 등)인 경우 False를 반환합니다.
        뉴스가 없거나 중립적이면 일단 매수 가능(True)으로 판단합니다.
        """
        if not self.is_available() or not headlines:
            return True # AI 없거나 뉴스 없으면 기본 통과
            
        news_text = "\n".join([f"- {h}" for h in headlines])
        
        prompt = f"""
당신은 한국 주식 단타 트레이더입니다. 다음은 오늘 아침 '{name}' 종목의 최근 뉴스 헤드라인입니다.
이 뉴스가 해당 종목에 치명적인 악재(예: 유상증자, 횡령/배임, 대주주 매도, 실적 어닝쇼크, 임상 실패 등)인지 판별하세요.
단순 하락 뉴스나 중립 뉴스는 통과(True)시키고, 절대 매수하면 안 되는 명백한 악재일 경우에만 실패(False)로 처리하세요.

[뉴스 헤드라인]
{news_text}

결과는 반드시 JSON 형식으로 아래와 같이 응답하세요. 다른 설명은 제외하세요.
{{
    "passed": true 또는 false,
    "reason": "악재인 경우 짧은 이유, 아니면 '이상 없음'"
}}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful AI JSON output generator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=150,
            )
            
            content = response.choices[0].message.content.strip()
            # 마크다운 코드 블록 제거
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
                
            result = json.loads(content)
            passed = result.get("passed", True)
            reason = result.get("reason", "")
            
            if not passed:
                logger.warning(f"[AI 검증 탈락] {name}({ticker}) 악재 감지: {reason}")
            else:
                logger.info(f"[AI 검증 통과] {name}({ticker}) 뉴스 이상 없음")
                
            return passed
            
        except Exception as e:
            logger.error(f"[{name}] 뉴스 검증 중 오류: {e}")
            return True # 오류 시 기본 통과

    def validate_pattern_context(self, ticker: str, pattern_type: str, ohlcv_text: str) -> bool:
        """
        패턴(휩소, 돌파, 눌림목)이 발생했을 때 직전 캔들들의 OHLCV 데이터를 텍스트로 분석하여
        이것이 가짜 신호(속임수)인지 진짜 세력 매집 패턴인지 승인합니다.
        """
        if not self.is_available():
            return True
            
        prompt = f"""
당신은 시스템 트레이딩 봇의 최종 승인자입니다. 방금 {pattern_type} 전략 타점이 포착되었습니다.
아래는 직전 5~10개 분봉의 OHLCV(시가/고가/저가/종가/거래량) 데이터입니다.

[분봉 데이터 시퀀스]
{ohlcv_text}

전략 설명:
- 전략 A (휩소): 하락 시 거래량이 급감하다가 마지막에 망치형 캔들이나 상승장악형이 나와야 함.
- 전략 B (돌파): 박스 돌파 시 거래량이 크게 터져야 함.
- 전략 C (눌림목): 돌파 후 하락할 때 거래량이 확 줄어들며 지지받아야 함.
- 전략 D (시가 회복): 시가를 이탈했다가 다시 위로 강하게 뚫어주며 매수세가 유입되어야 함.

위 데이터를 보고, 이 패턴이 전형적인 세력 개입의 진짜 패턴인지 판별하세요.
결과는 반드시 JSON 형식으로 아래와 같이 응답하세요.
{{
    "approved": true 또는 false,
    "reason": "승인/거절의 짧은 이유"
}}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise trading pattern validator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=150,
            )
            
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"): content = content[7:-3].strip()
            elif content.startswith("```"): content = content[3:-3].strip()
                
            result = json.loads(content)
            approved = result.get("approved", True)
            reason = result.get("reason", "")
            
            if not approved:
                logger.info(f"[{ticker}] AI 패턴 승인 거부 (전략 {pattern_type}): {reason}")
            else:
                logger.info(f"[{ticker}] AI 패턴 승인 완료 (전략 {pattern_type})")
                
            return approved
            
        except Exception as e:
            logger.error(f"[{ticker}] 패턴 검증 중 오류: {e}")
            return True
