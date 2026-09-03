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
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

import requests

ACTOR = "curious_coder~facebook-ads-library-scraper"
MAX_ADS = 24


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


def _normalize(item):
    """Apify 원본 아이템(snapshot.images/videos) → 프론트 da-item 카드가 기대하는
    {u,t,type} 형태로 변환. w/h(원본 해상도)는 이 액터 응답에 없어 생략(프론트는
    없으면 aspect-ratio 없이 렌더)."""
    snap = item.get("snapshot") or {}
    body = ((snap.get("body") or {}).get("text") or "")[:400]
    out = []
    for im in (snap.get("images") or []):
        url = im.get("original_image_url") or im.get("resized_image_url")
        if url:
            out.append({"u": url, "t": body, "type": "image"})
    for v in (snap.get("videos") or []):
        url = v.get("video_preview_image_url")
        if url:
            out.append({"u": url, "t": body, "type": "video"})
    return out


def collect(kw, country="KR", max_ads=MAX_ADS, logs=None, page_url=None):
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
    logs.append("[apify] 완료 kw=%s images=%d" % (kw, len(images)))
    return {"kw": kw, "images": images, "count": len(images),
            "at": time.strftime("%Y-%m-%d %H:%M"), "source": "apify_live",
            "precise": bool(page_url)}


def _raw_sample(kw, page_url):
    """타입 판정 검증용 — 원본 아이템의 display_format·이미지/영상/카드 수·snapshot 키."""
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return {"err": "no token"}
    url = page_url or _ad_library_url(kw)
    try:
        r = requests.post("https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items" % ACTOR,
                          params={"token": token}, json={"urls": [{"url": url}], "count": 6}, timeout=55)
        items = r.json()
    except Exception as e:
        return {"err": str(e)[:120]}
    out = []
    for it in items[:6]:
        snap = it.get("snapshot") or {}
        imgs, vids = (snap.get("images") or []), (snap.get("videos") or [])
        out.append({
            "display_format": snap.get("display_format"),
            "n_images": len(imgs), "n_videos": len(vids), "n_cards": len(snap.get("cards") or []),
            "video_has_url": bool(vids and (vids[0].get("video_hd_url") or vids[0].get("video_sd_url"))),
            "snap_keys": sorted(snap.keys())[:22],
        })
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        kw = _fix_kr((qs.get("kw", [""])[0] or "").strip())
        name = _fix_kr((qs.get("name", [""])[0] or "").strip()) or kw
        page_url = _fix_kr((qs.get("url", [""])[0] or "").strip())
        debug = (qs.get("debug", [""])[0] or "").strip() in ("1", "true", "yes")
        if not kw and not page_url:
            return self._send({"error": "kw 또는 url이 필요합니다"}, 400)
        logs = []
        try:
            res = collect(kw or name, logs=logs, page_url=page_url or None)
        except Exception as e:
            return self._send({"error": str(e)[:200], "logs": logs}, 500)
        if res is None:
            return self._send({"error": "미설정 또는 수집 실패", "logs": logs}, 503)
        res["name"] = name
        if debug:
            res["logs"] = logs
        # 원본 구조 진단(타입 판정 검증용): ?raw=1
        if (qs.get("raw", [""])[0] or "").strip() in ("1", "true"):
            res["_raw"] = _raw_sample(kw or name, page_url or None)
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
