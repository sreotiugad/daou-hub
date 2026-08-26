"""
Daou Hub 데이터 파이프라인 설정.

핵심 아이디어
  광고 API를 프론트가 직접 부르지 않는다. 무거운 수집은 하루 1번만 돌고,
  그 결과(RAW)는 구글시트에 누적된다. 이 파이프라인은
      구글시트 RAW  →  집계  →  daou-universe/data.json
  을 만들고, 프론트(app.html)는 그 data.json만 읽어 즉시 렌더한다.

환경변수가 없으면 build_data 는 자동으로 '샘플' data.json 을 만든다.
따라서 키가 없어도 사이트는 데모로 돌고, 키를 넣으면 실데이터로 바뀐다.
"""
import os
import json

# ── 출력 ───────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO_ROOT, "data.json")

# 프론트가 기대하는 최근 일수(일별 배열 길이). 프론트는 14/30/90/365로 잘라 씀.
PERIOD_DAYS = 365

# ── 브랜드 계층 (서비스명 → 대분류/세부브랜드) ──────────
# RAW 시트의 '서비스' 컬럼 값이 여기 키와 일치해야 한다.
BRAND_MAP = {
    "사방넷":       ("사방넷", "사방넷"),
    "사방넷미니":   ("사방넷", "사방넷미니"),
    "풀필먼트":     ("사방넷", "풀필먼트"),
    "애드콘":       ("애드콘", "애드콘"),
    "엔팩스":       ("애드콘", "엔팩스"),
    "다우오피스":   ("다우오피스", "다우오피스"),
    "다우오피스HR": ("다우오피스", "다우오피스HR"),
}
# 대분류 → 세부브랜드 순서 (프론트 탭/표 순서)
GROUP_SUBS = {
    "사방넷": ["사방넷", "사방넷미니", "풀필먼트"],
    "애드콘": ["애드콘", "엔팩스"],
    "다우오피스": ["다우오피스", "다우오피스HR"],
}
GROUPS = ["사방넷", "애드콘", "다우오피스"]

# 캠페인유형 표준 6종 (프론트 CT_ORDER 와 동일)
CT_ORDER = ["브랜드검색", "파워링크", "쇼핑검색", "구글검색", "실적최대화", "동영상"]

# RAW 시트 원본 캠페인유형 → 표준 6종 매핑 (adcon_report 의 type_ko 반영)
def norm_ct(raw: str, media: str = "") -> str:
    s = str(raw or "").strip()
    if "브랜드" in s:
        return "브랜드검색"
    if "파워링크" in s:
        return "파워링크"
    if "쇼핑" in s:
        return "쇼핑검색"
    if "실적" in s or "최대화" in s or "PMax" in s or "PERFORMANCE" in s.upper():
        return "실적최대화"
    if "동영상" in s or "VIDEO" in s.upper():
        return "동영상"
    if "검색" in s or "SEARCH" in s.upper():
        # 네이버 일반 검색은 파워링크, 구글 검색은 구글검색
        return "구글검색" if str(media).strip() == "구글" else "파워링크"
    # 디스플레이 등 나머지 → 매체 기준 기본 버킷
    return "구글검색" if str(media).strip() == "구글" else "파워링크"

# ── RAW 시트 컬럼 매핑 (실제 헤더가 다르면 env 로 덮어쓰기) ──
#   COL_* 환경변수로 각 컬럼 헤더명을 바꿀 수 있다.
# 기본값은 ADEF 데일리 리포트의 'raw' 시트 실제 헤더에 맞춤(띄어쓰기 포함).
# 브랜드 파일마다 헤더가 조금 다르면 env COL_* 로 덮어쓴다.
COLS = {
    "service":  os.environ.get("COL_SERVICE", "서비스"),
    "media":    os.environ.get("COL_MEDIA", "매체"),
    "camptype": os.environ.get("COL_CAMPTYPE", "캠페인 유형"),
    "date":     os.environ.get("COL_DATE", "기간"),
    "date_alt": os.environ.get("COL_DATE_ALT", "날짜"),
    "imp":      os.environ.get("COL_IMP", "노출 수"),
    "click":    os.environ.get("COL_CLICK", "클릭 수"),
    "cost":     os.environ.get("COL_COST", "광고비(마크업포함,VAT포함)"),
    "cost_alt": os.environ.get("COL_COST_ALT", "총 비용"),
    "signup":   os.environ.get("COL_SIGNUP", "가입"),
}

# ── 구글시트 접근 ───────────────────────────────────────
# 여러 시트에 나눠 적재할 수 있으니(예: 다우오피스는 별도 시트) 콤마로 여러 ID 지원
SHEET_IDS = [s.strip() for s in (os.environ.get("DAOU_SHEET_ID") or os.environ.get("MAPPING_SHEET_ID", "")).split(",") if s.strip()]
SHEET_ID = SHEET_IDS[0] if SHEET_IDS else ""   # sheet_writer(append) 는 첫 시트에 쓴다
SHEET_WORKSHEET = os.environ.get("DAOU_SHEET_WORKSHEET", "raw")

def service_account_info():
    """서비스계정 JSON. GA4_SERVICE_ACCOUNT_JSON(문자열/딕셔너리) 또는
    GOOGLE_APPLICATION_CREDENTIALS(파일 경로) 를 지원."""
    raw = os.environ.get("GA4_SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        except Exception:
            pass
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def sheet_ready() -> bool:
    return bool(SHEET_IDS and service_account_info())

# ── 네이버 검색광고 (키워드툴/실검색량) ─────────────────
def naver_account():
    cid = os.environ.get("NAVER1_CUSTOMER_ID")
    key = os.environ.get("NAVER1_API_KEY")
    sec = os.environ.get("NAVER1_SECRET_KEY")
    if cid and key and sec:
        return {"customer_id": cid, "api_key": key, "secret_key": sec}
    return None

# 경쟁 분석에서 미리 계산해 둘 키워드(프리셋 + 필요시 추가)
KEYWORDS = [k.strip() for k in os.environ.get(
    "DAOU_KEYWORDS",
    "그룹웨어,전자결재,쇼핑몰 통합관리,재고관리 프로그램,채용 사이트,모바일 쿠폰"
).split(",") if k.strip()]

# 광고 경쟁현황 표에서 '우리'로 강조할 브랜드
OUR_BRAND = os.environ.get("DAOU_OUR_BRAND", "다우오피스")
