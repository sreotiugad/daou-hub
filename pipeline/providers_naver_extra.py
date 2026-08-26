"""네이버 추가 실데이터 소스.

1) DataLab 검색어트렌드  → 12개월 추이·성별·연령 (상대지수 기반, 총량은 키워드툴에 앵커)
   필요: NAVER_DEV_CLIENT_ID / NAVER_DEV_CLIENT_SECRET  (네이버 개발자센터 앱)
2) 검색 API(blog/cafe)   → 콘텐츠 발행량(문서수)
   필요: 위 개발자 앱 동일 키
3) 검색광고 Estimate     → 예상 입찰가(CPC)
   필요: NAVER1_* (검색광고, 키워드툴과 동일)

시간대별(0~23시)은 어떤 공개 API도 제공하지 않으므로 항상 모델 추정.
모든 함수는 실패 시 None → 상위에서 모델값 유지.
"""
import os
import time
import json
import hmac
import base64
import hashlib
from datetime import date
import requests

DEV_ID = lambda: os.environ.get("NAVER_DEV_CLIENT_ID", "")
DEV_SECRET = lambda: os.environ.get("NAVER_DEV_CLIENT_SECRET", "")
DATALAB = "https://openapi.naver.com/v1/datalab/search"
SEARCH = "https://openapi.naver.com/v1/search/{}.json"
SEARCHAD = "https://api.searchad.naver.com"

# DataLab 연령대 코드 → 프론트 6버킷
AGE_BUCKETS = [
    ("10대", ["1", "2"]),
    ("20대", ["3", "4"]),
    ("30대", ["5", "6"]),
    ("40대", ["7", "8"]),
    ("50대", ["9", "10"]),
    ("60+", ["11"]),
]


def _dev_headers():
    return {"X-Naver-Client-Id": DEV_ID(), "X-Naver-Client-Secret": DEV_SECRET(),
            "Content-Type": "application/json"}


def _datalab_sum(kw, extra):
    """DataLab 호출 후 ratio 합계 반환(상대 비교용). 실패 시 None."""
    end = date.today()
    start = date(end.year - 1, end.month, 1)
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "timeUnit": "month",
            "keywordGroups": [{"groupName": kw, "keywords": [kw]}]}
    body.update(extra)
    try:
        r = requests.post(DATALAB, headers=_dev_headers(), data=json.dumps(body), timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()["results"][0]["data"]
        return sum(float(x["ratio"]) for x in data), data
    except Exception:
        return None


def datalab(kw, total, m_share, logs=None):
    """추이(12개월 절대 근사)·성별·연령. 개발자 키 없으면 None."""
    logs = logs if logs is not None else []
    if not (DEV_ID() and DEV_SECRET()):
        return None
    base = _datalab_sum(kw, {})
    if not base:
        logs.append(f"[datalab] {kw} 기본 추이 실패")
        return None
    _, series = base
    ratios = [float(x["ratio"]) for x in series]
    mx = max(ratios) or 1
    trend = []
    for rt in ratios[-12:]:
        v = rt / mx * total
        trend.append({"pc": round(v * (1 - m_share)), "mob": round(v * m_share)})
    while len(trend) < 12:
        trend.insert(0, {"pc": 0, "mob": 0})

    # 성별
    male = female = None
    gm = _datalab_sum(kw, {"gender": "m"})
    gf = _datalab_sum(kw, {"gender": "f"})
    if gm and gf:
        sm, sf = gm[0], gf[0]
        tot = (sm + sf) or 1
        male = round(sm / tot * 100)
        female = 100 - male

    # 연령 (6버킷)
    age = None
    sums = []
    ok = True
    for _, codes in AGE_BUCKETS:
        s = _datalab_sum(kw, {"ages": codes})
        if not s:
            ok = False
            break
        sums.append(s[0])
        time.sleep(0.1)
    if ok and sum(sums) > 0:
        t = sum(sums)
        age = [round(x / t * 100) for x in sums]

    logs.append(f"[datalab] {kw} trend=OK gender={'OK' if male is not None else '-'} age={'OK' if age else '-'}")
    out = {"trend": trend}
    if male is not None:
        out["male"], out["female"] = male, female
    if age:
        out["age"] = age
    return out


def content_count(kw, logs=None):
    """블로그+카페 문서수 = 콘텐츠 발행량. 개발자 키 없으면 None."""
    logs = logs if logs is not None else []
    if not (DEV_ID() and DEV_SECRET()):
        return None
    total = 0
    got = False
    for kind in ("blog", "cafearticle"):
        try:
            r = requests.get(SEARCH.format(kind), headers=_dev_headers(),
                             params={"query": kw, "display": 1}, timeout=10)
            if r.status_code == 200:
                total += int(r.json().get("total", 0))
                got = True
        except Exception:
            pass
    if not got:
        return None
    logs.append(f"[search] {kw} 콘텐츠 {total}건")
    return total


# ── 검색광고 Estimate (예상 입찰가) ──
def _sa_headers(acc, uri, method="POST"):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(hmac.new(str(acc["secret_key"]).encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"X-Timestamp": ts, "X-API-KEY": str(acc["api_key"]),
            "X-Customer": str(acc["customer_id"]), "X-Signature": sig,
            "Content-Type": "application/json"}


def estimate_cpc(kw, acc, logs=None):
    """평균 노출위치(2위) 예상 입찰가. 실패 시 None → 모델 추정 유지."""
    logs = logs if logs is not None else []
    if not acc:
        return None
    uri = "/estimate/average-position-bid/keyword"
    body = {"device": "MOBILE", "items": [{"key": kw.replace(" ", ""), "position": 2}]}
    try:
        r = requests.post(SEARCHAD + uri, headers=_sa_headers(acc, uri),
                          data=json.dumps(body), timeout=12)
        if r.status_code != 200:
            return None
        est = r.json().get("estimate", [])
        if est and est[0].get("bid"):
            return int(est[0]["bid"])
    except Exception as e:
        logs.append(f"[estimate] {kw} 오류: {e}")
    return None
