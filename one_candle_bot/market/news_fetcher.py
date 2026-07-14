import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

def fetch_recent_news(ticker: str, limit: int = 5) -> list[str]:
    """
    네이버 금융의 종목 메인 페이지에서 최근 뉴스 헤드라인을 수집합니다.
    """
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        headlines = []
        for a in soup.select('div.sub_section.news_section ul li a'):
            title = a.text.strip()
            # 관련 기사 링크 등 제외
            if title and not title.startswith("관련") and title not in headlines:
                headlines.append(title)
                if len(headlines) >= limit:
                    break
                    
        return headlines
    except Exception as e:
        logger.error(f"[{ticker}] 뉴스 수집 실패: {e}")
        return []
