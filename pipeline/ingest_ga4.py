"""GA4 → 하루치 전환(가입) → 표준 RAW 행. (다우오피스 전용)

다우오피스는 가입을 광고 전환이 아니라 GA4 키이벤트로 집계한다.
그래서 GA4 에서 '가입' 전환 수만 받아, 광고비 0짜리 전환 행으로 넣는다.
→ 브랜드 총 가입에만 더해지고(코스트 기반 차트엔 영향 없음), CPA=광고비/가입 이 맞게 된다.
(광고 수집기 쪽은 signup_from_ga4=true 로 가입을 0 처리해 중복을 막는다.)

계정: {label, property_id, service, conversion_event}
GA4_SERVICE_ACCOUNT_JSON 서비스계정에 해당 속성 뷰어 권한 필요.
라이브러리/키 없으면 [] 반환.
"""
import config as C


def _client(logs):
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.oauth2.service_account import Credentials
    except Exception as e:
        logs.append(f"[ga4] 라이브러리 미설치: {e}")
        return None
    info = C.service_account_info()
    if not info:
        logs.append("[ga4] 서비스계정(GA4_SERVICE_ACCOUNT_JSON) 없음 → 스킵")
        return None
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return BetaAnalyticsDataClient(credentials=creds)


def fetch_day(acc, date_iso, defaults, logs=None, _cache={}):
    logs = logs if logs is not None else []
    pid = str(acc.get("property_id", "")).strip()
    if not pid:
        logs.append(f"[ga4] {acc.get('label','?')} property_id 없음 → 스킵")
        return []
    client = _cache.get("c")
    if client is None:
        client = _client(logs)
        _cache["c"] = client or False
    if not client:
        return []
    try:
        from google.analytics.data_v1beta.types import (
            RunReportRequest, Dimension, Metric, DateRange,
            Filter, FilterExpression)
        ev = acc.get("conversion_event")
        dim_filter = None
        if ev:
            dim_filter = FilterExpression(filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(value=str(ev))))
        # 다우 리포트 앱과 동일: keyEvents 지표 + eventName 필터.
        metric_name = acc.get("conversion_metric") or "keyEvents"
        req = RunReportRequest(
            property=f"properties/{pid}",
            date_ranges=[DateRange(start_date=date_iso, end_date=date_iso)],
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name=metric_name)],
            dimension_filter=dim_filter,
        )
        resp = client.run_report(req)
        conv = 0.0
        for row in resp.rows:
            conv += float(row.metric_values[0].value or 0)
    except Exception as e:
        logs.append(f"[ga4] {acc.get('label','')} 오류: {e}")
        return []
    if conv <= 0:
        logs.append(f"[ga4] {acc.get('label','')} {date_iso} · 전환 0")
        return []
    svc = acc.get("service")
    logs.append(f"[ga4] {acc.get('label','')} {date_iso} · 가입 {conv}")
    return [{
        "서비스": svc, "매체": "구글", "캠페인 유형": "구글검색",
        "캠페인": f"GA4 전환({svc})", "기간": date_iso,
        "노출 수": 0, "클릭 수": 0, "총 비용": 0,
        "가입": conv, "광고비(마크업포함,VAT포함)": 0,
    }]
