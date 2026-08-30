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
    # 성과·가입을 (1)캠페인 (2)광고(ad_group_ad) 두 층위로 조회한다.
    #   가입 = conversion_action_category=SIGNUP 만. (conversion 세그먼트는 성과와 분리)
    #   광고 단위: 검색·쇼핑·디스플레이·동영상은 ad_group_ad 로 광고별. Pmax 는 광고가
    #   없어 ad_group_ad 에 안 잡히므로, 광고로 커버 안 된 캠페인만 캠페인 단위 폴백 →
    #   총 지출은 그대로 보존하고 중복 없이 광고 단위까지 확장.
    q_camp = ("SELECT campaign.name, campaign.advertising_channel_type, "
              "metrics.impressions, metrics.clicks, metrics.cost_micros "
              "FROM campaign WHERE segments.date = '%s'" % date_iso)
    q_ad = ("SELECT campaign.name, campaign.advertising_channel_type, ad_group.name, "
            "ad_group_ad.ad.id, ad_group_ad.ad.name, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros "
            "FROM ad_group_ad WHERE segments.date = '%s'" % date_iso)
    q_conv_c = ("SELECT campaign.name, segments.conversion_action_category, metrics.conversions "
                "FROM campaign WHERE segments.date = '%s'" % date_iso)
    q_conv_ad = ("SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, "
                 "segments.conversion_action_category, metrics.conversions "
                 "FROM ad_group_ad WHERE segments.date = '%s'" % date_iso)
    camp, adrows, conv_c, conv_ad = {}, {}, {}, {}
    try:   # 캠페인 단위(필수) — 실패 시 구글 스킵
        svc = client.get_service("GoogleAdsService")
        for batch in svc.search_stream(customer_id=cid, query=q_camp):
            for r in batch.results:
                d = camp.setdefault(r.campaign.name, {"imp": 0, "clk": 0, "net": 0.0,
                                    "chtp": r.campaign.advertising_channel_type.name})
                d["imp"] += int(r.metrics.impressions)
                d["clk"] += int(r.metrics.clicks)
                d["net"] += r.metrics.cost_micros / 1_000_000.0
        for batch in svc.search_stream(customer_id=cid, query=q_conv_c):
            for r in batch.results:
                if r.segments.conversion_action_category.name != "SIGNUP":
                    continue
                conv_c[r.campaign.name] = conv_c.get(r.campaign.name, 0.0) + float(r.metrics.conversions)
    except Exception as e:
        logs.append(f"[google-ads] {acc.get('label','')} 캠페인 쿼리 오류: {e}")
        return []
    try:   # 광고 단위(선택) — 실패해도 캠페인 단위로 폴백해 리포트 보존
        for batch in svc.search_stream(customer_id=cid, query=q_ad):
            for r in batch.results:
                k = (r.campaign.name, r.ad_group.name, str(r.ad_group_ad.ad.id))
                nm = (r.ad_group_ad.ad.name or "").strip() or f"광고 #{r.ad_group_ad.ad.id}"
                d = adrows.setdefault(k, {"imp": 0, "clk": 0, "net": 0.0,
                                     "chtp": r.campaign.advertising_channel_type.name,
                                     "adg": r.ad_group.name, "ad": nm})
                d["imp"] += int(r.metrics.impressions)
                d["clk"] += int(r.metrics.clicks)
                d["net"] += r.metrics.cost_micros / 1_000_000.0
        for batch in svc.search_stream(customer_id=cid, query=q_conv_ad):
            for r in batch.results:
                if r.segments.conversion_action_category.name != "SIGNUP":
                    continue
                k = (r.campaign.name, r.ad_group.name, str(r.ad_group_ad.ad.id))
                conv_ad[k] = conv_ad.get(k, 0.0) + float(r.metrics.conversions)
    except Exception as e:
        logs.append(f"[google-ads] {acc.get('label','')} 광고단위 쿼리 실패(캠페인단위 폴백): {str(e)[:80]}")
        adrows.clear(); conv_ad.clear()
    ga4 = acc.get("signup_from_ga4")
    covered = {k[0] for k in adrows}   # 광고 단위로 커버된 캠페인

    def _row(name, chtp, adg, ad, imp, clk, net, sval):
        return {
            "서비스": ad_config.resolve_service(acc, name), "매체": "구글",
            "캠페인 유형": C.norm_ct(_CHTP.get(chtp, "구글검색"), "구글"),
            "캠페인": name, "광고그룹": adg, "광고": ad, "기간": date_iso,
            "노출 수": imp, "클릭 수": clk, "총 비용": int(round(net)),
            "가입": round(0.0 if ga4 else sval, 1),
            "광고비(마크업포함,VAT포함)": ad_config.marked_cost(net, "구글", mk, vat),
        }
    rows = []
    for (cname, adg, adid), d in adrows.items():            # (a) 광고 단위
        if d["imp"] == 0 and d["clk"] == 0 and d["net"] == 0:
            continue
        rows.append(_row(cname, d["chtp"], adg, d["ad"], d["imp"], d["clk"], d["net"],
                         conv_ad.get((cname, adg, adid), 0.0)))
    for cname, d in camp.items():                            # (b) Pmax 등 광고없는 캠페인
        if cname in covered or (d["imp"] == 0 and d["clk"] == 0 and d["net"] == 0):
            continue
        rows.append(_row(cname, d["chtp"], "", "", d["imp"], d["clk"], d["net"],
                         conv_c.get(cname, 0.0)))
    logs.append(f"[google-ads] {acc.get('label','')} {date_iso} · {len(rows)}행(광고 {len(adrows)})")
    return rows
