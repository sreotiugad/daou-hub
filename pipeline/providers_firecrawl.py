"""Firecrawl(파이어크롤) → 네이버 검색결과(SERP) 실데이터 경쟁사 수집.

기존 광고 API(keywordstool/stats/datalab)로는 **얻을 수 없는** 두 가지를 채운다.
  1) 이 키워드로 실제 네이버에 노출되는 '파워링크' 광고주 + 광고 카피(순서대로)
  2) 자연검색 상위 경쟁 사이트(도메인)
헤드리스 브라우저로 JS 렌더 후 LLM 구조화 추출(formats=[{type:'json'}]).

키 없으면(=FIRECRAWL_API_KEY 미설정) None 반환 → 호출부는 모델 추정값을 유지.
어떤 예외(레이트리밋·타임아웃·파싱실패)도 삼켜서 None → 리포트는 절대 깨지지 않는다.

필요 환경변수: FIRECRAWL_API_KEY (firecrawl.dev · 무료 500크레딧/월, 1 scrape=1크레딧)
"""
import os
import time
import requests

API = "https://api.firecrawl.dev/v2/scrape"

# '우리' 브랜드 판별용 힌트(서비스명 + 도메인 조각). 광고주/사이트가 우리면 us=True.
_OUR_DOMAINS = ("sabangnet", "daou", "ddnews", "ppurio", "bizmailer",
                "npax", "addcon", "adwel")


def _key():
    return os.environ.get("FIRECRAWL_API_KEY") or ""


def _is_us(text, our_names):
    t = str(text or "").lower()
    for n in our_names:
        n = str(n or "").strip()
        if n and n.lower() in t:
            return True
    for d in _OUR_DOMAINS:
        if d in t:
            return True
    return False


def _domain(url):
    s = str(url or "").split("//")[-1].split("/")[0].strip()
    return s[4:] if s.startswith("www.") else s


_SCHEMA = {
    "type": "object",
    "properties": {
        "ads": {
            "type": "array",
            "description": "'파워링크' 광고 영역의 광고들, 노출된 순서대로",
            "items": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string", "description": "광고주/업체명"},
                    "headline": {"type": "string", "description": "광고 제목"},
                    "description": {"type": "string", "description": "광고 설명문구"},
                    "url": {"type": "string", "description": "표시 URL"},
                },
            },
        },
        "organic": {
            "type": "array",
            "description": "자연검색(비광고) 상위 웹사이트 결과, 순서대로",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
}

_PROMPT = (
    "이 네이버 검색결과 페이지에서 두 가지를 추출해줘. "
    "(1) ads: 상단·하단 '파워링크' 광고 영역에 실제 노출된 광고를 노출 순서대로 "
    "— 광고주/업체명(brand), 광고 제목(headline), 설명문구(description), 표시 URL(url). 최대 10개. "
    "(2) organic: 광고가 아닌 일반 웹사이트/사이트 검색 결과의 title·url을 상위 순서대로 최대 8개. "
    "블로그·카페·지식iN·뉴스 섹션은 organic 에서 제외하고 사이트/웹 결과만. 없으면 빈 배열."
)


def serp_competitors(kw, our_names=None, logs=None, timeout=45):
    """키워드 하나의 네이버 SERP 경쟁사. 실패/키없음 → None."""
    logs = logs if logs is not None else []
    if not _key():
        return None
    our_names = our_names or []
    url = "https://search.naver.com/search.naver?query=" + requests.utils.quote(kw)
    body = {
        "url": url,
        "formats": [{"type": "json", "schema": _SCHEMA, "prompt": _PROMPT}],
        "onlyMainContent": False,          # 파워링크는 본문 밖 영역이라 포함시켜야 함
        "waitFor": 3500,                    # JS 렌더 대기
        "location": {"country": "KR", "languages": ["ko"]},
        "blockAds": False,                  # SERP 광고는 우리가 원하는 데이터라 차단 X
    }
    try:
        r = requests.post(API, json=body, timeout=timeout,
                          headers={"Authorization": "Bearer " + _key(),
                                   "Content-Type": "application/json"})
        if r.status_code != 200:
            logs.append(f"[firecrawl] {kw} status={r.status_code} {r.text[:120]}")
            return None
        data = (r.json() or {}).get("data") or {}
        j = data.get("json") or {}
    except Exception as e:
        logs.append(f"[firecrawl] {kw} 오류: {str(e)[:100]}")
        return None

    ads_raw = j.get("ads") or []
    org_raw = j.get("organic") or []
    ads, organic = [], []
    seen = set()
    for a in ads_raw:
        name = str(a.get("brand", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        copy = str(a.get("headline", "")).strip() or str(a.get("description", "")).strip()
        u = str(a.get("url", "")).strip()
        ads.append({"name": name, "copy": copy, "url": u,
                    "us": _is_us(name + " " + u + " " + copy, our_names)})
        if len(ads) >= 10:
            break
    dseen = set()
    for o in org_raw:
        u = str(o.get("url", "")).strip()
        dom = _domain(u)
        if not dom or dom in dseen:
            continue
        dseen.add(dom)
        organic.append({"title": str(o.get("title", "")).strip(), "url": u, "domain": dom,
                        "us": _is_us(u + " " + str(o.get("title", "")), our_names)})
        if len(organic) >= 8:
            break
    if not ads and not organic:
        logs.append(f"[firecrawl] {kw} 추출 0건(빈 SERP?)")
        return None
    logs.append(f"[firecrawl] {kw} 광고 {len(ads)} · 자연검색 {len(organic)} 실수집")
    return {"ads": ads, "organic": organic}
