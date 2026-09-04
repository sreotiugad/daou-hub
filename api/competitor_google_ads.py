"""Vercel 서버리스 함수 — 경쟁사 Google 광고 소재 온디맨드(실시간) 조회.

Meta 쪽(api/competitor_ads.py)과 짝을 이루는 구글 버전. Google Ads Transparency
Center는 '광고주 이름'이 아니라 '도메인' 또는 'advertiser ID' 로만 조회된다.
그래서 경쟁사 등록 정보의 홈페이지(home) / 투명성센터 URL(google) 에서 도메인이나
advertiser ID를 뽑아 조회한다.

액터: experthasan/google-ads-transparency-api
  - pay-per-result $5/1,000 (월 렌탈 없음 → 아무 APIFY_TOKEN 으로 즉시 실행 가능)
  - 입력: {searchType, domain|advertiserId, countryCode, format, limit, maxPages}
  - 출력 item: {advertiser_name, format_type, original_url,
                variants:[{image, content, format}], start, last_seen}
  - 이미지 URL은 tpc.googlesyndication.com/simgad/... (공개 CDN, 세션 무관)

  /api/competitor_google_ads?home=<홈페이지>&url=<투명성센터URL>&name=<표시명>
  (domain= 직접 지정도 가능. debug=1 이면 진단 로그 포함)

프론트(index.html renderDA의 Google 탭)는 사용자가 Google 탭을 눌렀을 때만
이 엔드포인트를 호출한다(불필요한 유료 실행 방지).
"""
import os
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

ACTOR = "experthasan~google-ads-transparency-api"
MAX_ADS = 24
KST = timezone(timedelta(hours=9))
_now_kst = lambda: datetime.now(KST).strftime("%Y-%m-%d %H:%M")   # Vercel 서버는 UTC라 KST로 보정


def _fix_kr(s):
    try:
        return s.encode("latin-1").decode("utf-8")
    except UnicodeError:
        try:
            return s.encode("utf-8", "surrogateescape").decode("utf-8")
        except UnicodeError:
            return s


def _host_to_domain(host):
    host = (host or "").strip().lower()
    if not host:
        return None
    if "//" not in host and "/" in host:
        host = host.split("/", 1)[0]
    if "//" in host:
        host = urlparse(host if "://" in host else "http://" + host).netloc
    host = host.split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _resolve_target(domain, google_url, home):
    """(searchType, key) 결정. advertiser ID 우선, 없으면 도메인.
    반환 예: ('advertiser_id', 'AR123...') 또는 ('domain', 'nike.com')."""
    # 1) 투명성센터 URL 에서 advertiser ID / domain 추출
    if google_url:
        try:
            u = urlparse(google_url)
            # .../advertiser/AR123?... 형태
            for seg in (u.path or "").split("/"):
                if seg.startswith("AR") and seg[2:].isdigit():
                    return ("advertiser_id", seg)
            q = parse_qs(u.query)
            if q.get("advertiserId"):
                return ("advertiser_id", q["advertiserId"][0].strip())
            if q.get("domain"):
                d = _host_to_domain(q["domain"][0])
                if d:
                    return ("domain", d)
        except Exception:
            pass
    # 2) 직접 지정한 domain
    d = _host_to_domain(domain)
    if d:
        return ("domain", d)
    # 3) 공식 홈페이지 도메인
    d = _host_to_domain(home)
    if d:
        return ("domain", d)
    return (None, None)


def _normalize(item):
    """experthasan 출력 item → 프론트 da-item 카드 {u,t,type} 리스트.
    variants[] 안에 크리에이티브별 image(정지 이미지)와 format 이 들어있다."""
    name = item.get("advertiser_name") or ""
    ftype = (item.get("format_type") or "").lower()
    out = []
    for v in (item.get("variants") or []):
        img = v.get("image")
        if not img:
            continue
        f = (v.get("format") or ftype or "").lower()
        ty = "video" if "video" in f else "image"
        out.append({"u": img, "t": name, "type": ty})
    return out


def collect(target, country="KR", max_ads=MAX_ADS, logs=None):
    logs = logs if logs is not None else []
    stype, key = target
    if not key:
        logs.append("⚠️ [google] 도메인/advertiser 를 확인할 수 없음 (홈페이지 URL 등록 필요)")
        return None
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        logs.append("⚠️ [google] APIFY_TOKEN 없음 — 건너뜀")
        return None
    payload = {"searchType": stype, "countryCode": country,
               "format": "ALL", "limit": 40, "maxPages": 1}
    payload["advertiserId" if stype == "advertiser_id" else "domain"] = key
    logs.append("[google] 조회 %s=%s" % (stype, key))
    try:
        r = requests.post(
            "https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items" % ACTOR,
            params={"token": token},
            json=payload,
            timeout=55,
        )
    except Exception as e:
        logs.append("❌ [google] 요청 실패: %s" % str(e)[:200])
        return None
    if r.status_code >= 400:
        logs.append("❌ [google] status=%s body=%s" % (r.status_code, r.text[:200]))
        return None
    try:
        items = r.json()
    except Exception:
        logs.append("❌ [google] JSON 파싱 실패")
        return None
    images, seen = [], set()
    for it in items:
        for im in _normalize(it):
            if im["u"] in seen:
                continue
            seen.add(im["u"])
            images.append(im)
            if len(images) >= max_ads:
                break
        if len(images) >= max_ads:
            break
    logs.append("[google] 완료 %s=%s images=%d" % (stype, key, len(images)))
    return {"target": "%s:%s" % (stype, key), "images": images,
            "count": len(images), "at": _now_kst(),
            "source": "apify_google_live", "precise": True}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        gv = lambda k: _fix_kr((qs.get(k, [""])[0] or "").strip())
        name = gv("name")
        target = _resolve_target(gv("domain"), gv("url"), gv("home"))
        debug = gv("debug") in ("1", "true", "yes")
        if not target[1]:
            return self._send({"error": "도메인 또는 홈페이지 URL이 필요합니다",
                               "images": []}, 400)
        logs = []
        try:
            res = collect(target, logs=logs)
        except Exception as e:
            return self._send({"error": str(e)[:200], "logs": logs}, 500)
        if res is None:
            return self._send({"error": "미설정 또는 수집 실패", "images": [],
                               "logs": logs}, 503)
        res["name"] = name
        if debug:
            res["logs"] = logs
        self._send(res, 200)

    def _send(self, obj, code):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
