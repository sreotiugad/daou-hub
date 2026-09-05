"""Vercel 서버리스 함수 — 경쟁사 Google 광고 소재 온디맨드(실시간) 조회.

Apify(experthasan)에서 **ScrapeCreators**로 교체(2026-09-05). 이유: experthasan은
Apify 액터라 Meta와 같은 Apify 월 한도 지갑을 공유 → 구글($5/1000)이 그 지갑을
반복적으로 태웠다. ScrapeCreators는 완전히 별도 계정/과금이라 Apify 한도와 무관.

액터 대신 REST API:
  GET https://api.scrapecreators.com/v1/google/company/ads
    ?domain=<도메인>&region=KR&format=image&topic=all
  헤더: x-api-key: <SCRAPECREATORS_API_KEY>
  - format=image → 디스플레이 배너만(텍스트·검색 광고 클러터 원천 차단)
  - 기본 검색 1크레딧/요청(get_ad_details=25크레딧은 안 씀), 무료 100크레딧
  - 응답 ads[]: {advertiserId, creativeId, format, adUrl, advertiserName,
                 imageUrl(tpc.googlesyndication, image 광고만), firstShown, lastShown}

경쟁사 등록 정보의 홈페이지(home)/투명성센터 URL(google)에서 도메인·advertiser ID를
뽑아 조회한다. 프론트(index.html loadGoogle)는 "구글 광고 불러오기" 버튼을 눌렀을 때만
이 엔드포인트를 호출한다(유료 실행 최소화). 성공 응답은 CDN 24h 캐시.

  /api/competitor_google_ads?home=<홈페이지>&url=<투명성센터URL>&name=<표시명>
  (domain= 직접 지정도 가능. debug=1 이면 진단 로그 포함)
"""
import os
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

API_URL = "https://api.scrapecreators.com/v1/google/company/ads"
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
    if google_url:
        try:
            u = urlparse(google_url)
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
    d = _host_to_domain(domain)
    if d:
        return ("domain", d)
    d = _host_to_domain(home)
    if d:
        return ("domain", d)
    return (None, None)


def _parse_ts(s):
    """'2024-03-15' / ISO8601('...T..Z' / '+09:00') / unix → epoch초 (실패 시 None)."""
    if isinstance(s, (int, float)) and s > 0:
        return float(s)
    if not (isinstance(s, str) and s.strip()):
        return None
    t = s.strip().replace("T", " ")
    t = t.split(".")[0].split("+")[0].replace("Z", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _perf(ad):
    """성과 프록시: 얼마나 오래·최근까지 집행했는가(광고주는 안 먹히는 소재를 바로 끔).
    Google은 is_active가 없어 lastShown이 최근(≤10일)이면 활성으로 본다."""
    sd = _parse_ts(ad.get("firstShown"))
    ls = _parse_ts(ad.get("lastShown"))
    days, act, since = None, False, None
    now = datetime.now(timezone.utc).timestamp()
    if sd:
        end = ls if (ls and ls > sd) else now
        days = int((end - sd) // 86400)
        since = datetime.fromtimestamp(sd, timezone.utc).strftime("%Y-%m-%d")
        if ls and (now - ls) <= 10 * 86400:
            act = True
    return {"days": days, "act": act, "since": since}


def _normalize(ads):
    """ScrapeCreators ads[] → 프론트 da-item {u,t,type,성과}. imageUrl 없는 광고(텍스트 등)는 건너뜀."""
    out = []
    for ad in ads:
        img = ad.get("imageUrl")
        if not img:
            continue
        f = (ad.get("format") or "").lower()
        ty = "video" if "video" in f else ("text" if "text" in f else "image")
        p = _perf(ad)
        out.append({"u": img, "t": ad.get("advertiserName") or "", "type": ty,
                    "days": p["days"], "act": p["act"], "since": p["since"]})
    return out


def collect(target, country="KR", max_ads=MAX_ADS, logs=None, probe=False):
    logs = logs if logs is not None else []
    stype, key = target
    if not key:
        logs.append("⚠️ [google] 도메인/advertiser 를 확인할 수 없음 (홈페이지 URL 등록 필요)")
        return None
    api_key = os.environ.get("SCRAPECREATORS_API_KEY")
    if not api_key:
        logs.append("⚠️ [google] SCRAPECREATORS_API_KEY 없음 — 건너뜀")
        return None
    params = {"topic": "all", "region": country, "format": "image"}
    params["advertiser_id" if stype == "advertiser_id" else "domain"] = key
    logs.append("[google] 조회 %s=%s (scrapecreators)" % (stype, key))
    try:
        r = requests.get(API_URL, params=params,
                         headers={"x-api-key": api_key}, timeout=45)
    except Exception as e:
        logs.append("❌ [google] 요청 실패: %s" % str(e)[:200])
        return None
    if r.status_code >= 400:
        logs.append("❌ [google] status=%s body=%s" % (r.status_code, r.text[:200]))
        return None
    try:
        data = r.json()
    except Exception:
        logs.append("❌ [google] JSON 파싱 실패")
        return None
    ads = data.get("ads") or []
    logs.append("[google] ads=%d credits_remaining=%s" % (len(ads), data.get("credits_remaining")))
    images, seen = [], set()
    for im in _normalize(ads):
        if im["u"] in seen:
            continue
        seen.add(im["u"])
        images.append(im)
        if len(images) >= max_ads:
            break
    images.sort(key=lambda im: (1 if im.get("act") else 0, im.get("days") or -1), reverse=True)
    dl = [im["days"] for im in images if isinstance(im.get("days"), int)]
    perf_sum = {"maxDays": max(dl) if dl else None,
                "active": sum(1 for im in images if im.get("act")),
                "winners": sum(1 for d in dl if d >= 30)}
    logs.append("[google] 완료 %s=%s images=%d perf=%s" % (stype, key, len(images), perf_sum))
    if probe and ads:
        logs.append("PROBE:" + json.dumps(ads[0], ensure_ascii=False)[:500])
    return {"target": "%s:%s" % (stype, key), "images": images,
            "count": len(images), "perf": perf_sum, "at": _now_kst(),
            "source": "scrapecreators_live", "precise": True}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        gv = lambda k: _fix_kr((qs.get(k, [""])[0] or "").strip())
        name = gv("name")
        target = _resolve_target(gv("domain"), gv("url"), gv("home"))
        debug = gv("debug") in ("1", "true", "yes")
        probe = gv("probe") in ("1", "true", "yes")
        if not target[1]:
            return self._send({"error": "도메인 또는 홈페이지 URL이 필요합니다",
                               "images": []}, 400)
        logs = []
        try:
            res = collect(target, logs=logs, probe=probe)
        except Exception as e:
            return self._send({"error": str(e)[:200], "logs": logs}, 500)
        if res is None:
            return self._send({"error": "미설정 또는 수집 실패", "images": [],
                               "logs": logs}, 503)
        res["name"] = name
        if debug or probe:
            res["logs"] = logs
        self._send(res, 200)

    def _send(self, obj, code):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 소재가 담긴 성공만 CDN 캐시(24h) → 반복 조회 유료 실행 방지. 실패·0건은 캐시 금지.
        if code == 200 and (obj.get("count") or 0) > 0:
            self.send_header("Cache-Control", "public, s-maxage=86400, stale-while-revalidate=172800")
        else:
            self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
