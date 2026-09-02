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


_PROMO_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "페이지 대표 헤드라인"},
        "summary": {"type": "string", "description": "이 페이지가 지금 밀고 있는 핵심 메시지 한 줄"},
        "promos": {
            "type": "array",
            "description": "현재 진행 중인 프로모션/혜택",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "할인/무료체험/이벤트/증정/기타"},
                    "headline": {"type": "string", "description": "프로모션 제목"},
                    "detail": {"type": "string", "description": "혜택 상세"},
                    "price": {"type": "string", "description": "가격·할인율(있으면)"},
                    "cta": {"type": "string", "description": "행동유도 버튼 문구"},
                    "deadline": {"type": "string", "description": "종료일/기간(있으면)"},
                },
            },
        },
    },
}

_PROMO_PROMPT = (
    "이 페이지에서 지금 진행 중인 프로모션·혜택을 추출해줘. "
    "각 프로모션의 종류(할인/무료체험/이벤트/증정/기타), 제목(headline), 상세(detail), "
    "가격·할인율(price), 행동유도 문구(cta), 종료일/기간(deadline). "
    "그리고 페이지 대표 헤드라인(headline)과, 이 페이지가 지금 밀고 있는 핵심 메시지를 한 줄로(summary). "
    "프로모션이 없으면 promos는 빈 배열."
)


def scrape_promo(url, logs=None, timeout=45):
    """프로모션/랜딩 페이지 스냅샷. 현재 혜택·가격·CTA·헤드라인. 실패/키없음 → None."""
    logs = logs if logs is not None else []
    if not _key() or not url:
        return None
    body = {
        "url": url,
        "formats": [{"type": "json", "schema": _PROMO_SCHEMA, "prompt": _PROMO_PROMPT}],
        "onlyMainContent": True,
        "waitFor": 3000,
        "location": {"country": "KR", "languages": ["ko"]},
    }
    try:
        r = requests.post(API, json=body, timeout=timeout,
                          headers={"Authorization": "Bearer " + _key(),
                                   "Content-Type": "application/json"})
        if r.status_code != 200:
            logs.append(f"[firecrawl] promo {url} status={r.status_code} {r.text[:100]}")
            return None
        data = (r.json() or {}).get("data") or {}
        j = data.get("json") or {}
    except Exception as e:
        logs.append(f"[firecrawl] promo {url} 오류: {str(e)[:100]}")
        return None
    promos = []
    for p in (j.get("promos") or []):
        hd = str(p.get("headline", "")).strip()
        dt = str(p.get("detail", "")).strip()
        if not (hd or dt):
            continue
        promos.append({"kind": str(p.get("kind", "")).strip() or "기타",
                       "headline": hd, "detail": dt,
                       "price": str(p.get("price", "")).strip(),
                       "cta": str(p.get("cta", "")).strip(),
                       "deadline": str(p.get("deadline", "")).strip()})
        if len(promos) >= 8:
            break
    out = {"headline": str(j.get("headline", "")).strip(),
           "summary": str(j.get("summary", "")).strip(),
           "promos": promos}
    logs.append(f"[firecrawl] promo {url} · 프로모션 {len(promos)}건")
    return out


_ADS_SCHEMA = {
    "type": "object",
    "properties": {
        "ads": {
            "type": "array",
            "description": "이 광고주가 현재 게재/노출 중인 광고들",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "description": "광고 크리에이티브 대표 이미지의 실제 src URL(http로 시작)"},
                    "headline": {"type": "string", "description": "광고 제목/헤드라인"},
                    "body": {"type": "string", "description": "광고 본문/기본 텍스트"},
                    "cta": {"type": "string", "description": "행동유도 버튼 문구(예: 더 알아보기)"},
                    "platform": {"type": "string", "description": "게재 지면(Facebook/Instagram/검색/디스플레이/YouTube 등)"},
                    "started": {"type": "string", "description": "게재 시작일(있으면)"},
                    "status": {"type": "string", "description": "활성/비활성"},
                },
            },
        },
    },
}

_ADS_PROMPT = (
    "이 페이지는 광고 투명성 센터 또는 광고 라이브러리야. 이 광고주가 지금 게재 중인 광고들을 추출해줘. "
    "각 광고 카드에서 image 는 **실제 광고 크리에이티브(상품·캠페인 메인 이미지, 카드에서 가장 큰 이미지)의 <img> src**만 넣어. "
    "카드 상단의 **광고주 프로필 사진·로고·아바타(작은 원형/정사각 썸네일)는 절대 image 로 쓰지 마.** "
    "그 외 headline(헤드라인), body(본문 텍스트), cta(버튼 문구), platform(게재 지면), started(시작일), status(상태). "
    "http 로 시작하는 실제 URL만. 최대 12개. 페이지 UI 아이콘은 제외."
)


def scrape_ads(url, logs=None, timeout=27):
    """Meta 광고 라이브러리 / Google 광고 투명성센터 페이지 → 게재 광고 소재(이미지·카피).
    JS 무한스크롤·봇차단으로 실패할 수 있음 → 실패/키없음/URL없음 시 None.
    timeout 은 Vercel 함수 상한(30s)보다 짧게 잡아 504 대신 깔끔한 None 이 되게 한다.
    (콜드 스크랩이 잘려도 Firecrawl 이 서버측에 캐시 → 프론트 재시도 시 빠르게 성공)"""
    logs = logs if logs is not None else []
    if not _key() or not url:
        return None
    body = {
        "url": url,
        "formats": ["markdown", {"type": "json", "schema": _ADS_SCHEMA, "prompt": _ADS_PROMPT}],
        "onlyMainContent": False,
        "waitFor": 4000,               # 광고 라이브러리 로드 대기(30s 상한 고려해 단축)
        "location": {"country": "KR", "languages": ["ko"]},
    }
    try:
        r = requests.post(API, json=body, timeout=timeout,
                          headers={"Authorization": "Bearer " + _key(),
                                   "Content-Type": "application/json"})
        if r.status_code != 200:
            logs.append(f"[firecrawl] ads {url[:60]} status={r.status_code} {r.text[:100]}")
            return None
        data = (r.json() or {}).get("data") or {}
        j = data.get("json") or {}
        md = data.get("markdown") or ""
    except Exception as e:
        logs.append(f"[firecrawl] ads {url[:60]} 오류: {str(e)[:100]}")
        return None
    # LLM 환각 방지: 페이지에서 광고를 못 읽으면 example.com·placeholder 이미지나
    # 뻔한 문구를 지어낸다. 가짜 이미지는 버리고, 진짜 이미지가 하나도 없으면 실패로 본다.
    _FAKE = ("example.com", "example.org", "example.net", "placeholder", "lorempix",
             "via.placeholder", "yourdomain", "dummyimage", "/ad1.", "/ad2.", "/ad3.")
    # 프로필사진·로고·아바타 경로(광고 소재 아님) — Meta/IG CDN 패턴
    _PROFILE = ("t51.2885-19", "t39.30808", "t1.6435-9", "/profile", "avatar", "logo",
                "s60x60", "p60x60", "s100x100", "p100x100", "s120x120", "p148x148", "s148x148")

    def _real_img(u):
        u = str(u or "").strip()
        if not u.startswith("http"):
            return ""
        lo = u.lower()
        if any(f in lo for f in _FAKE) or any(p in lo for p in _PROFILE):
            return ""
        return u

    ads = []
    for a in (j.get("ads") or []):
        img = _real_img(a.get("image"))
        hd = str(a.get("headline", "")).strip()
        bd = str(a.get("body", "")).strip()
        if not (img or hd or bd):
            continue
        ads.append({"image": img, "headline": hd, "body": bd,
                    "cta": str(a.get("cta", "")).strip(),
                    "platform": str(a.get("platform", "")).strip(),
                    "started": str(a.get("started", "")).strip(),
                    "status": str(a.get("status", "")).strip()})
        if len(ads) >= 12:
            break
    n_img = sum(1 for a in ads if a["image"])
    logs.append(f"[firecrawl] ads {url[:50]} · 소재 {len(ads)}개(진짜이미지 {n_img}) · md {len(md)}자")
    # 진짜 이미지가 0개면 = 렌더 실패/환각으로 간주 → 링크 폴백하도록 None
    if n_img == 0:
        return None
    ads = [a for a in ads if a["image"]]   # 이미지 있는 소재만(갤러리용)
    return {"ads": ads, "imgCount": n_img}
