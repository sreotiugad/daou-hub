"""메타(Facebook/Instagram) 광고 → 하루치 캠페인 실적 → 표준 RAW 행.

Graph API insights. 사방넷 리포트 앱과 동일 규칙:
  - 매체 = 메타
  - 캠페인유형 = objective 가 VIDEO 계열이면 동영상, 그 외 디스플레이
  - 가입 = actions 중 action_type == complete_registration 합
  - 광고비 = spend 그대로 (VAT 조정 없음)

계정: {label, access_token, ad_account_id, service, service_rules?, markup?, vat?}
키 없으면 [] 반환.
"""
import json
import requests
import ad_config
import config as C

GRAPH = "https://graph.facebook.com/v21.0"
VIDEO_OBJ = {"VIDEO_VIEWS", "OUTCOME_VIDEO_VIEWS"}
CONV_ACTIONS = {"complete_registration"}


def fetch_day(acc, date_iso, defaults, logs=None):
    logs = logs if logs is not None else []
    token = acc.get("access_token")
    acct = acc.get("ad_account_id")
    if not (token and acct):
        logs.append(f"[meta] {acc.get('label','?')} 토큰/계정 없음 → 스킵")
        return []
    account = acct if str(acct).startswith("act_") else f"act_{acct}"
    url = f"{GRAPH}/{account}/insights"
    params = {
        "access_token": token,
        "fields": "campaign_name,objective,impressions,clicks,spend,actions",
        "time_range": json.dumps({"since": date_iso, "until": date_iso}),
        "time_increment": "1", "level": "campaign", "limit": "500",
    }
    mk, vat = ad_config.markup_vat(acc, defaults)
    rows = []
    try:
        while True:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code != 200:
                logs.append(f"[meta] {acc.get('label','')} status={r.status_code} {r.text[:160]}")
                break
            j = r.json()
            for it in j.get("data", []):
                obj = str(it.get("objective", "")).upper()
                ct = "동영상" if obj in VIDEO_OBJ else "디스플레이"
                conv = sum(float(a.get("value", 0) or 0) for a in (it.get("actions") or [])
                           if a.get("action_type") in CONV_ACTIONS)
                imp = int(float(it.get("impressions", 0) or 0))
                clk = int(float(it.get("clicks", 0) or 0))
                spend = float(it.get("spend", 0) or 0)
                if imp == 0 and clk == 0 and spend == 0:
                    continue
                name = str(it.get("campaign_name", ""))
                rows.append({
                    "서비스": ad_config.resolve_service(acc, name),
                    "매체": "메타",
                    "캠페인 유형": ct,
                    "캠페인": name,
                    "기간": date_iso,
                    "노출 수": imp,
                    "클릭 수": clk,
                    "총 비용": int(round(spend)),
                    "가입": conv,
                    "광고비(마크업포함,VAT포함)": ad_config.marked_cost(spend, "메타", mk, vat),
                })
            nxt = (j.get("paging") or {}).get("next")
            if not nxt:
                break
            url, params = nxt, {}
    except Exception as e:
        logs.append(f"[meta] {acc.get('label','')} 오류: {e}")
        return rows
    logs.append(f"[meta] {acc.get('label','')} {date_iso} · {len(rows)}행")
    return rows
