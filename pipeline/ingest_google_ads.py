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
    # 기존 스트림릿 앱과 동일한 GADS_* 이름도 그대로 받아먹는다.
    def ev(name):
        return os.environ.get("GOOGLE_ADS_" + name) or os.environ.get("GADS_" + name)
    need = ["DEVELOPER_TOKEN", "CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"]
    if not all(ev(k) for k in need):
        logs.append("[google-ads] 공통 OAuth 환경변수 없음(GOOGLE_ADS_*/GADS_*) → 스킵")
        return None
    cfg = {
        "developer_token": ev("DEVELOPER_TOKEN"),
        "client_id": ev("CLIENT_ID"),
        "client_secret": ev("CLIENT_SECRET"),
        "refresh_token": ev("REFRESH_TOKEN"),
        "use_proto_plus": True,
    }
    lc = ev("LOGIN_CUSTOMER_ID")
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
    # 성과(노출·클릭·비용)와 가입(전환)을 분리 조회한다.
    #   가입 = conversion_action_category = SIGNUP 인 전환만 (실제 브랜드 리포트 동일).
    #   conversion 카테고리로 세그먼트하면 성과 지표가 중복되므로 쿼리를 나눈다.
    q_perf = (
        "SELECT campaign.name, campaign.advertising_channel_type, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros "
        "FROM campaign WHERE segments.date = '%s'" % date_iso
    )
    q_conv = (
        "SELECT campaign.name, segments.conversion_action_category, metrics.conversions "
        "FROM campaign WHERE segments.date = '%s'" % date_iso
    )
    perf, signup = {}, {}
    try:
        svc = client.get_service("GoogleAdsService")
        for batch in svc.search_stream(customer_id=cid, query=q_perf):
            for r in batch.results:
                name = r.campaign.name
                d = perf.setdefault(name, {"imp": 0, "clk": 0, "net": 0.0,
                                          "chtp": r.campaign.advertising_channel_type.name})
                d["imp"] += int(r.metrics.impressions)
                d["clk"] += int(r.metrics.clicks)
                d["net"] += r.metrics.cost_micros / 1_000_000.0
        for batch in svc.search_stream(customer_id=cid, query=q_conv):
            for r in batch.results:
                if r.segments.conversion_action_category.name != "SIGNUP":
                    continue
                signup[r.campaign.name] = signup.get(r.campaign.name, 0.0) + float(r.metrics.conversions)
    except Exception as e:
        logs.append(f"[google-ads] {acc.get('label','')} 쿼리 오류: {e}")
        return []
    rows = []
    for name, d in perf.items():
        if d["imp"] == 0 and d["clk"] == 0 and d["net"] == 0:
            continue
        rows.append({
            "서비스": ad_config.resolve_service(acc, name),
            "매체": "구글",
            "캠페인 유형": C.norm_ct(_CHTP.get(d["chtp"], "구글검색"), "구글"),
            "캠페인": name,
            "기간": date_iso,
            "노출 수": d["imp"],
            "클릭 수": d["clk"],
            "총 비용": int(round(d["net"])),
            "가입": round(signup.get(name, 0.0), 1),
            "광고비(마크업포함,VAT포함)": ad_config.marked_cost(d["net"], "구글", mk, vat),
        })
    logs.append(f"[google-ads] {acc.get('label','')} {date_iso} · {len(rows)}행")
    return rows
