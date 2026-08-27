"""구글애즈 → 하루치 캠페인 실적 → 표준 RAW 행.

google-ads 파이썬 라이브러리(GAQL)를 쓴다. 공통 인증(개발자토큰·OAuth)은
환경변수로, 계정별 customer_id 는 accounts.json 으로 분리.

필요 환경변수(공통, 시크릿):
  GOOGLE_ADS_DEVELOPER_TOKEN
  GOOGLE_ADS_CLIENT_ID
  GOOGLE_ADS_CLIENT_SECRET
  GOOGLE_ADS_REFRESH_TOKEN
  (선택) GOOGLE_ADS_LOGIN_CUSTOMER_ID   MCC 매니저 계정 ID

라이브러리/키 없으면 [] 반환(파이프라인 계속 진행).
주의(라이브 보정): cost_micros=순비용 가정, metrics.conversions=가입 가정.
"""
import os
import ad_config
import config as C

_CHTP = {
    "SEARCH": "구글검색", "SHOPPING": "쇼핑검색", "VIDEO": "동영상",
    "PERFORMANCE_MAX": "실적최대화", "DISPLAY": "구글검색",
    "MULTI_CHANNEL": "실적최대화",
}


def _client(logs):
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except Exception as e:
        logs.append(f"[google-ads] 라이브러리 미설치: {e}")
        return None
    need = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"]
    if not all(os.environ.get(k) for k in need):
        logs.append("[google-ads] 공통 OAuth 환경변수 없음 → 스킵")
        return None
    cfg = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    lc = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if lc:
        cfg["login_customer_id"] = lc.replace("-", "")
    try:
        return GoogleAdsClient.load_from_dict(cfg)
    except Exception as e:
        logs.append(f"[google-ads] client 초기화 실패: {e}")
        return None


def fetch_day(acc, date_iso, defaults, logs=None, _client_cache={}):
    logs = logs if logs is not None else []
    client = _client_cache.get("c")
    if client is None:
        client = _client(logs)
        _client_cache["c"] = client or False
    if not client:
        return []
    cid = str(acc.get("customer_id", "")).replace("-", "")
    if not cid:
        logs.append(f"[google-ads] {acc.get('label','?')} customer_id 없음 → 스킵")
        return []
    mk, vat = ad_config.markup_vat(acc, defaults)
    q = (
        "SELECT campaign.name, campaign.advertising_channel_type, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        "FROM campaign WHERE segments.date = '%s'" % date_iso
    )
    rows = []
    try:
        svc = client.get_service("GoogleAdsService")
        for batch in svc.search_stream(customer_id=cid, query=q):
            for r in batch.results:
                imp = int(r.metrics.impressions)
                clk = int(r.metrics.clicks)
                net = r.metrics.cost_micros / 1_000_000.0
                conv = float(r.metrics.conversions)
                if imp == 0 and clk == 0 and net == 0:
                    continue
                name = r.campaign.name
                chtp = _CHTP.get(r.campaign.advertising_channel_type.name, "구글검색")
                rows.append({
                    "서비스": ad_config.resolve_service(acc, name),
                    "매체": "구글",
                    "캠페인 유형": C.norm_ct(chtp, "구글"),
                    "캠페인": name,
                    "기간": date_iso,
                    "노출 수": imp,
                    "클릭 수": clk,
                    "총 비용": int(round(net)),
                    "가입": conv,
                    "광고비(마크업포함,VAT포함)": ad_config.marked_cost(net, mk, vat),
                })
    except Exception as e:
        logs.append(f"[google-ads] {acc.get('label','')} 쿼리 오류: {e}")
        return []
    logs.append(f"[google-ads] {acc.get('label','')} {date_iso} · {len(rows)}행")
    return rows
