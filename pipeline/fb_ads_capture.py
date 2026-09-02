"""Meta 광고 라이브러리 → 같은 세션에서 광고 소재 이미지 캡처(검증/수집).

핵심: 렌더(Playwright)와 다운로드를 **같은 러너(같은 IP/세션)** 에서 하면
fbcdn 서명(URL signature)이 일치해 403 없이 받아진다. (Vercel/Firecrawl 처럼
렌더와 다운로드 컨텍스트가 다르면 'URL signature mismatch' 발생.)

지금 단계 = 검증: 이미지 몇 개 찾고, 몇 개가 같은 세션에서 실제로 다운로드되는지,
실패 시 status/본문을 기록해 pipeline/_capture_result.json 에 남긴다.
(다음 단계에서 Vercel Blob 업로드 + 매니페스트로 확장)

환경변수: CAPTURE_KW (검색어). 없으면 인자 또는 기본값.
"""
import os
import re
import sys
import json
import time
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

KW = os.environ.get("CAPTURE_KW") or (sys.argv[1] if len(sys.argv) > 1 else "브이티")
URL = ("https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=KR&q="
       + urllib.request.quote(KW)
       + "&sort_data[direction]=desc&sort_data[mode]=relevancy_monthly_grouped"
       + "&search_type=keyword_unordered&media_type=all")

_PROFILE = ("t51.2885-19", "t39.30808-1", "s60x60", "p60x60", "s100x100", "p148x148", "s148x148")


def _is_profile(s):
    s = s.lower()
    return any(x in s for x in _PROFILE)


def dl_urllib(url):
    """유저 스크립트(urlretrieve)와 동일 방식 — 러너 IP에서 직접 GET."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
    r = urllib.request.urlopen(req, timeout=15)
    return r.getcode(), r.read()


def main():
    from playwright.sync_api import sync_playwright
    headed = os.environ.get("CAPTURE_HEADED", "1") != "0"
    res = {"kw": KW, "headed": headed, "adEls": 0, "imgFound": 0, "allImgs": 0,
           "downloaded": 0, "method": "urllib(same-runner)",
           "title": "", "finalUrl": "", "bodyText": "", "failures": [], "samples": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=[
            "--no-sandbox", "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage"])
        ctx = browser.new_context(locale="ko-KR", user_agent=UA,
                                  viewport={"width": 1440, "height": 1000})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        # 쿠키/동의 배너 있으면 닫기(베스트에포트)
        for label in ["모든 쿠키 허용", "필수 쿠키만 허용", "쿠키 허용", "Allow all cookies",
                      "Only allow essential cookies", "Accept all", "허용"]:
            try:
                b = page.get_by_role("button", name=label)
                if b.count() > 0:
                    b.first.click(timeout=2500)
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                pass
        # 스크롤로 광고 로드
        last = 0
        for _ in range(8):
            page.mouse.wheel(0, 24000)
            page.wait_for_timeout(2000)
            h = page.evaluate("document.body.scrollHeight")
            if h == last:
                break
            last = h
        # 진단
        try:
            res["title"] = (page.title() or "")[:80]
            res["finalUrl"] = page.url[:120]
            res["bodyText"] = (page.evaluate("document.body.innerText") or "")[:300].replace("\n", " ")
            res["allImgs"] = page.eval_on_selector_all("img", "els => els.length")
        except Exception as e:
            res["diagErr"] = str(e)[:80]
        try:
            res["adEls"] = page.eval_on_selector_all("div._7jvw", "els => els.length")
        except Exception:
            pass
        # 광고 크리에이티브 이미지 src 수집(클래스 대신 fbcdn 패턴으로 견고하게)
        srcs = page.eval_on_selector_all(
            "img", "els => els.map(e=>e.src).filter(s=>s && s.includes('fbcdn') && s.includes('scontent'))")
        srcs = [s for s in dict.fromkeys(srcs) if not _is_profile(s)]
        res["imgFound"] = len(srcs)
        for s in srcs[:15]:
            try:
                code, data = dl_urllib(s)
                if code == 200 and len(data) > 500:
                    res["downloaded"] += 1
                    if len(res["samples"]) < 3:
                        res["samples"].append({"host": s.split("/")[2], "bytes": len(data)})
                else:
                    if len(res["failures"]) < 5:
                        res["failures"].append({"status": code, "host": s.split("/")[2]})
            except Exception as e:
                msg = str(e)
                body = ""
                m = re.search(r"HTTP Error (\d+)", msg)
                if len(res["failures"]) < 5:
                    res["failures"].append({"err": msg[:70]})
            time.sleep(0.2)
        browser.close()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    with open(os.path.join(os.path.dirname(__file__), "_capture_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
