"""Vercel 서버리스 함수 — 경쟁사 Meta 광고 소재 온디맨드(실시간) 조회.

comp-ads/manifest.json(GitHub Actions "FB Ads Capture" 수동 트리거로만 갱신되는
정적 캡처)의 대안. Apify curious_coder/facebook-ads-library-scraper 액터를
요청 시점에 그때그때 호출해 임의 경쟁사 키워드에 대해 즉시 결과를 돌려준다.

실측(2026-09-03, 키워드 "브이티" 기준):
  - run-sync-get-dataset-items 응답 ~10초, 광고 10건
  - 반환되는 fbcdn 이미지 URL은 GraphQL 응답 기반이라 세션/IP 무관하게 다운로드
    가능(서명 만료까지 ~4일 여유) — DOM 스크래핑 방식(fb_ads_capture.py)이 겪던
    "렌더·다운로드 세션 불일치 → 403" 문제가 없음
  - 비용: 광고 1,000건당 $0.75 (Apify pay-per-event)

  /api/competitor_ads?kw=<검색어>&name=<표시용 이름>

프론트(index.html DUComp.renderDA)는 이 엔드포인트를 우선 호출하고,
APIFY_TOKEN 미설정이거나 실패하면 기존 comp-ads/manifest.json 정적 캡처로 폴백한다.
"""
import os
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

import requests

ACTOR = "curious_coder~facebook-ads-library-scraper"
MAX_ADS = 24
KST = timezone(timedelta(hours=9))
_now_kst = lambda: datetime.now(KST).strftime("%Y-%m-%d %H:%M")   # Vercel 서버는 UTC라 KST로 보정


def _fix_kr(s):
    """Vercel 쿼리스트링 한글 mojibake 복원 (api/competitor.py 와 동일)."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except UnicodeError:
        try:
            return s.encode("utf-8", "surrogateescape").decode("utf-8")
        except UnicodeError:
            return s


def _ad_library_url(kw, country="KR"):
    return ("https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
            "&country=%s&q=%s&search_type=keyword_unordered&media_type=all" % (country, quote(kw)))


_BAD_DOM = ("facebook.com", "instagram.com", "fb.com", "l.facebook.com",
            "fb.me", "wa.me", "youtube.com", "linktr.ee")


def _ad_domain(snap):
    """광고주 본인 도메인 추출: Meta 광고의 caption('themedicube.co.kr')이나 link_url.
    이건 광고주가 자기 광고에 직접 건 랜딩이라 그 브랜드의 실제 도메인 = Google
    투명성센터 조회(도메인 기준)에 그대로 쓸 수 있다."""
    cap = (snap.get("caption") or "").strip().lower()
    host = None
    if cap and "." in cap and " " not in cap:
        host = cap.split("/")[0]
    if not host:
        lu = snap.get("link_url") or ""
        try:
            host = urlparse(lu if "://" in lu else "http://" + lu).netloc.lower()
        except Exception:
            host = None
    if not host:
        return None
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or any(host == b or host.endswith("." + b) for b in _BAD_DOM):
        return None
    return host


def _perf(item):
    """성과 프록시: 광고를 얼마나 오래·계속 집행 중인지.
    광고주는 안 먹히는 소재를 바로 끄므로, 오래·활성 집행 = 그 브랜드에게 검증된 승자.
    Meta는 경쟁사 실성과(CTR·전환)를 공개하지 않으니 이것이 유일하게 정직한 신호.
      days = 집행 일수(활성이면 오늘까지, 종료면 종료일까지)
      act  = 현재 집행 중 여부
      since= 집행 시작일(YYYY-MM-DD)"""
    sd = item.get("start_date")
    ed = item.get("end_date")
    act = bool(item.get("is_active"))
    days = None
    if isinstance(sd, (int, float)) and sd > 0:
        now = datetime.now(timezone.utc).timestamp()
        end = ed if (isinstance(ed, (int, float)) and ed > sd) else now
        if act:                       # 활성 광고는 지금 이 순간까지 계속 집행 중
            end = max(end, now)
        days = int((end - sd) // 86400)
    since = (item.get("start_date_formatted") or "")[:10] or None
    return {"days": days, "act": act, "since": since}


def _normalize(item):
    """Apify 원본 아이템 → 프론트 da-item 카드가 기대하는 {u,t,type,...} 리스트.
    ⚠️ 이미지 광고(캐러셀·DPA·DCO)는 크리에이티브를 snapshot.cards[] 에 담는다.
    images/videos 만 읽으면 그런 이미지 광고를 통째로 놓쳐 '전부 영상'으로 보인다.
    videos·images·cards 를 모두 훑고, 각 크리에이티브를 영상/이미지로 판정한다.
    각 카드에 광고 단위 성과 프록시(집행기간·활성)를 함께 붙인다."""
    snap = item.get("snapshot") or {}
    body = ((snap.get("body") or {}).get("text") or "")[:400]
    perf = _perf(item)
    out = []

    def add(url, ty, vurl=None):
        # url = 카드에 표시할 정지 이미지(영상이면 포스터). vurl = 실제 재생용 영상 파일 URL.
        if url:
            d = {"u": url, "t": body, "type": ty,
                 "days": perf["days"], "act": perf["act"], "since": perf["since"]}
            if vurl:
                d["v"] = vurl          # 프론트에서 <video>로 호버 재생
            out.append(d)

    for v in (snap.get("videos") or []):
        add(v.get("video_preview_image_url"), "video",
            v.get("video_hd_url") or v.get("video_sd_url"))
    for im in (snap.get("images") or []):
        add(im.get("original_image_url") or im.get("resized_image_url"), "image")
    # 카드(캐러셀·DPA·DCO): 카드마다 영상이면 poster+영상URL, 아니면 이미지
    for c in (snap.get("cards") or []):
        vu = c.get("video_preview_image_url")
        if vu:
            add(vu, "video", c.get("video_hd_url") or c.get("video_sd_url"))
        else:
            add(c.get("original_image_url") or c.get("resized_image_url"), "image")
    return out


def _raw_probe(item):
    """(임시) 실데이터에서 날짜/활성 필드 키·값을 확인하기 위한 요약."""
    def summ(d):
        o = {}
        for k, v in d.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                o[k] = v
            elif isinstance(v, list):
                o[k] = "[list %d]" % len(v)
            elif isinstance(v, dict):
                o[k] = "{keys: %s}" % ",".join(list(v.keys())[:14])
        return o
    snap = item.get("snapshot") or {}
    return {"top": summ(item), "snapshot": summ(snap)}


def collect(kw, country="KR", max_ads=MAX_ADS, logs=None, page_url=None, probe=False):
    """page_url(경쟁사가 직접 등록한 정확한 Meta 광고 라이브러리/페이지 URL)이 있으면
    그 광고주 페이지의 광고만 정확히 가져온다. 없을 때만 키워드 텍스트 검색으로
    폴백하는데, 이 경우 그 키워드가 언급된 무관한 제3자 광고까지 섞여 나올 수 있다
    (예: "브이티" 키워드 검색 시 관련 리셀러·후기 계정의 광고도 포함됨)."""
    logs = logs if logs is not None else []
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        logs.append("⚠️ [apify] APIFY_TOKEN 없음 — 건너뜀")
        return None
    if page_url:
        url = page_url
        logs.append("[apify] 광고주 페이지 URL로 정확히 조회")
    else:
        url = _ad_library_url(kw, country)
        logs.append("[apify] 키워드 검색(광고주 페이지 URL 미등록 — 무관 광고 섞일 수 있음)")
    try:
        r = requests.post(
            "https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items" % ACTOR,
            params={"token": token},
            json={"urls": [{"url": url}], "count": max_ads},
            timeout=55,
        )
    except Exception as e:
        logs.append("❌ [apify] 요청 실패: %s" % str(e)[:200])
        return None
    if r.status_code >= 400:
        logs.append("❌ [apify] status=%s body=%s" % (r.status_code, r.text[:200]))
        return None
    try:
        items = r.json()
    except Exception:
        logs.append("❌ [apify] JSON 파싱 실패")
        return None
    images, seen = [], set()
    fmt_dist = {}          # snapshot.display_format 분포(진짜 타입 확인용)
    dom_dist = {}          # 광고주 도메인 분포(Google 조회에 자동 재사용)
    for it in items:
        snap = it.get("snapshot") or {}
        df = (snap.get("display_format") or "?")
        if snap:
            fmt_dist[df] = fmt_dist.get(df, 0) + 1
            dm = _ad_domain(snap)
            if dm:
                dom_dist[dm] = dom_dist.get(dm, 0) + 1
        for im in _normalize(it):
            if im["u"] in seen:
                continue
            seen.add(im["u"])
            images.append(im)
            if len(images) >= max_ads:
                break
        if len(images) >= max_ads:
            break
    # 승자(오래·활성 집행) 소재를 앞으로: 활성 우선 → 집행일수 내림차순
    images.sort(key=lambda im: (1 if im.get("act") else 0, im.get("days") or -1), reverse=True)
    dl = [im["days"] for im in images if isinstance(im.get("days"), int)]
    perf_sum = {"maxDays": max(dl) if dl else None,
                "active": sum(1 for im in images if im.get("act")),
                "winners": sum(1 for d in dl if d >= 30)}   # 30일+ 집행 = 검증 소재
    ad_domain = max(dom_dist, key=dom_dist.get) if dom_dist else None   # 최빈 광고주 도메인
    logs.append("[apify] 완료 kw=%s images=%d formats=%s perf=%s domain=%s" % (kw, len(images), fmt_dist, perf_sum, ad_domain))
    if probe and items:
        logs.append("PROBE:" + json.dumps(_raw_probe(items[0]), ensure_ascii=False))
    return {"kw": kw, "images": images, "count": len(images), "formats": fmt_dist,
            "perf": perf_sum, "adDomain": ad_domain, "at": _now_kst(),
            "source": "apify_live", "precise": bool(page_url)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        kw = _fix_kr((qs.get("kw", [""])[0] or "").strip())
        name = _fix_kr((qs.get("name", [""])[0] or "").strip()) or kw
        page_url = _fix_kr((qs.get("url", [""])[0] or "").strip())
        debug = (qs.get("debug", [""])[0] or "").strip() in ("1", "true", "yes")
        probe = (qs.get("probe", [""])[0] or "").strip() in ("1", "true", "yes")
        if not kw and not page_url:
            return self._send({"error": "kw 또는 url이 필요합니다"}, 400)
        logs = []
        try:
            res = collect(kw or name, logs=logs, page_url=page_url or None, probe=probe)
        except Exception as e:
            return self._send({"error": str(e)[:200], "logs": logs}, 500)
        if res is None:
            return self._send({"error": "미설정 또는 수집 실패", "logs": logs}, 503)
        res["name"] = name
        if debug or probe:
            res["logs"] = logs
        self._send(res, 200)

    def _send(self, obj, code):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 실시간 소재라 캐시하지 않음(다음 요청에서 최신 상태 반영 우선)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
