"""네이버 검색광고 → 하루치 캠페인 실적 → 표준 RAW 행.

접근:
  1) GET /ncc/campaigns          계정의 캠페인 목록(id·이름·유형)
  2) GET /stats                  그 캠페인들의 하루 실적(노출·클릭·비용·전환)
  3) 캠페인유형 매핑 + 마크업/VAT 적용 → RAW 행

인증: keywords_naver 와 동일한 HMAC 서명.
계정 없거나 호출 실패 시 [] 반환(파이프라인은 계속 진행).

가입(중요·브랜드별 상이):
  실제 브랜드 리포트는 /stats 의 ccnt(전체 전환)를 그대로 쓰지 않는다.
  - 애드콘: AD_CONVERSION 리포트에서 convType='sign_up' 만 필터 → adgroup 병합
  - 사방넷: AD_CONVERSION 을 전환일≠노출일 보정해 키워드 단위 합산
  - 다우오피스: 광고 전환이 아니라 GA4 키이벤트(속성별)로 가입 집계
  여기 ccnt 는 '전체 전환' 근사치다. 정확 매칭은 accounts 의 signup 규칙 +
  AD_CONVERSION 연동으로 첫 실행 때 보정한다. (RAW_RECIPES.md 참고)
광고비: salesAmt(VAT포함) ÷1.1 = ad_config.marked_cost(net,'네이버',...).
"""
import time
import hmac
import hashlib
import base64
import json
import requests
import ad_config
import config as C

BASE = "https://api.searchad.naver.com"

# 네이버 campaignTp → 표준 캠페인유형 힌트(한국어) → norm_ct
_CTP = {
    "WEB_SITE": "파워링크", "SHOPPING": "쇼핑검색", "BRAND_SEARCH": "브랜드검색",
    "BRAND_SEARCH_ADVANCED": "브랜드검색", "POWER_CONTENTS": "파워링크",
    "PLACE": "파워링크",
}


def _headers(acc, uri, method="GET"):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(
        hmac.new(str(acc["secret_key"]).encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    return {"X-Timestamp": ts, "X-API-KEY": str(acc["api_key"]),
            "X-Customer": str(acc["customer_id"]), "X-Signature": sig,
            "Content-Type": "application/json"}


def _campaigns(acc, logs):
    uri = "/ncc/campaigns"
    r = requests.get(BASE + uri, headers=_headers(acc, uri), timeout=20)
    if r.status_code != 200:
        logs.append(f"[naver-ads] {acc.get('label','')} campaigns status={r.status_code}")
        return []
    return r.json() or []


def _stats(acc, ids, date_iso, logs):
    """하루(since=until=date) 실적. 네이버 /stats 는 id(단수)로 하나씩 조회한다
    (실제 리포트 앱과 동일 — ids 배열은 'ID 형식 오류' 발생)."""
    uri = "/stats"
    # avgRnk = 평균노출순위(광고가 평균 몇 위에 노출됐는지). 노출가중 평균으로 캠페인 단위 산출.
    fields = json.dumps(["impCnt", "clkCnt", "salesAmt", "ccnt", "avgRnk"])
    tr = json.dumps({"since": date_iso, "until": date_iso})
    out = {}
    warned = False
    for cid in ids:
        params = {"id": cid, "fields": fields, "timeRange": tr, "timeIncrement": "1"}
        try:
            r = requests.get(BASE + uri, params=params, headers=_headers(acc, uri), timeout=25)
            if r.status_code != 200:
                if not warned:
                    logs.append(f"[naver-ads] stats status={r.status_code} {r.text[:120]}")
                    warned = True
                continue
            agg = {"impCnt": 0.0, "clkCnt": 0.0, "salesAmt": 0.0, "ccnt": 0.0}
            rnk_w = 0.0  # Σ(avgRnk × impCnt) — 노출가중
            for row in (r.json().get("data") or []):
                imp_r = float(row.get("impCnt", 0) or 0)
                for k in agg:
                    agg[k] += float(row.get(k, 0) or 0)
                rnk_r = float(row.get("avgRnk", 0) or 0)
                if rnk_r > 0:
                    rnk_w += rnk_r * imp_r
            agg["avgRnk"] = (rnk_w / agg["impCnt"]) if agg["impCnt"] > 0 else 0.0
            out[str(cid)] = agg
        except Exception as e:
            logs.append(f"[naver-ads] stats 오류: {e}")
    return out


def fetch_day(acc, date_iso, defaults, logs=None):
    logs = logs if logs is not None else []
    if not (acc.get("customer_id") and acc.get("api_key") and acc.get("secret_key")):
        logs.append(f"[naver-ads] {acc.get('label','?')} 키 없음 → 스킵")
        return []
    try:
        camps = _campaigns(acc, logs)
    except Exception as e:
        logs.append(f"[naver-ads] campaigns 오류: {e}")
        return []
    if not camps:
        return []
    by_id = {str(c.get("nccCampaignId")): c for c in camps}
    stats = _stats(acc, list(by_id.keys()), date_iso, logs)
    mk, vat = ad_config.markup_vat(acc, defaults)

    rows = []
    for cid, c in by_id.items():
        s = stats.get(cid)
        if not s:
            continue
        imp = float(s.get("impCnt", 0) or 0)
        clk = float(s.get("clkCnt", 0) or 0)
        net = float(s.get("salesAmt", 0) or 0)
        conv = 0.0 if acc.get("signup_from_ga4") else float(s.get("ccnt", 0) or 0)
        rnk = float(s.get("avgRnk", 0) or 0)
        if imp == 0 and clk == 0 and net == 0:
            continue
        name = c.get("name", "")
        ctp_hint = _CTP.get(str(c.get("campaignTp", "")), "파워링크")
        rows.append({
            "서비스": ad_config.resolve_service(acc, name),
            "매체": "네이버",
            "캠페인 유형": C.norm_ct(ctp_hint, "네이버"),
            "캠페인": name,
            "기간": date_iso,
            "노출 수": int(imp),
            "클릭 수": int(clk),
            "총 비용": int(net),
            "가입": conv,
            "광고비(마크업포함,VAT포함)": ad_config.marked_cost(net, "네이버", mk, vat),
            "평균노출순위": round(rnk, 2),
        })
    logs.append(f"[naver-ads] {acc.get('label','')} {date_iso} · {len(rows)}행")
    return rows
