"""Meta 광고 라이브러리 → 같은 세션에서 광고 소재 이미지 캡처 → repo 정적 저장.

핵심(검증 완료): 렌더(Playwright)와 이미지 다운로드를 **같은 GitHub Actions 러너**
(같은 IP/세션)에서 하면 fbcdn 서명이 일치해 403 없이 받아진다. Vercel/Firecrawl 처럼
렌더·다운로드 컨텍스트가 다르면 'URL signature mismatch' 로 실패.

동작:
  CAPTURE_KW(쉼표구분 경쟁사명) 각각에 대해
    → FB 광고 라이브러리 렌더 → 점진 스크롤로 광고 이미지(img+video poster) src 수집
    → 같은 러너에서 다운로드(중복 제거) → comp-ads/<slug>/NN.jpg 저장
    → comp-ads/manifest.json 갱신 (slug→{kw,count,images,at})
프론트는 manifest.json 을 읽어 경쟁사별 개별 소재 카드로 렌더.
"""
import os
import io
import sys
import json
import time
import hashlib
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTBASE = os.path.join(ROOT, "comp-ads")
MAX_PER = 24          # 경쟁사당 최대 저장 소재 수(repo 용량 관리)
_PROFILE = ("t51.2885-19", "t39.30808-1", "s60x60", "p60x60", "s100x100", "p148x148", "s148x148")


def slugify(kw):
    return hashlib.md5(kw.encode("utf-8")).hexdigest()[:12]


def _is_profile(s):
    s = s.lower()
    return any(x in s for x in _PROFILE)


def _dl(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
    r = urllib.request.urlopen(req, timeout=15)
    return r.getcode(), r.read()


def _dims(path):
    """저장한 소재의 (가로, 세로) 픽셀. 실패하면 (0, 0)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def _ocr(path):
    """광고 소재 안의 텍스트(한/영) 추출. tesseract 없으면 조용히 ''. (나중에 카피 분석·검색용)"""
    try:
        import pytesseract
        from PIL import Image
        txt = pytesseract.image_to_string(Image.open(path), lang="kor+eng")
        txt = " ".join(txt.split())        # 개행·중복공백 정리
        return txt[:400]
    except Exception:
        return ""


def capture_one(page, kw):
    url = ("https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=KR&q="
           + urllib.request.quote(kw)
           + "&sort_data[direction]=desc&sort_data[mode]=relevancy_monthly_grouped"
           + "&search_type=keyword_unordered&media_type=all")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    for label in ["모든 쿠키 허용", "필수 쿠키만 허용", "Allow all cookies", "허용"]:
        try:
            b = page.get_by_role("button", name=label)
            if b.count() > 0:
                b.first.click(timeout=2500)
                page.wait_for_timeout(1200)
                break
        except Exception:
            pass
    COLLECT = ("els => els.map(e=>e.currentSrc||e.src)"
               ".filter(s=>s && s.includes('fbcdn') && s.includes('scontent'))")
    VCOLLECT = ("els=>els.map(e=>e.poster||e.currentSrc||e.src)"
                ".filter(s=>s && s.includes('fbcdn') && s.includes('scontent'))")
    found = {}          # src → 최초 출처('img' = 이미지 소재 후보 / 'vid' = 동영상 poster)
    last_h, stable = 0, 0
    for step in range(70):
        for s in page.eval_on_selector_all("img", COLLECT):
            found.setdefault(s, "img")
        for s in page.eval_on_selector_all("video", VCOLLECT):
            found.setdefault(s, "vid")   # 이미 img 로 잡힌 건 덮어쓰지 않음
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(600)
        if step % 10 == 9:
            h = page.evaluate("document.body.scrollHeight")
            stable = stable + 1 if h == last_h else 0
            last_h = h
            if stable >= 2:
                break
    srcs = [(s, o) for s, o in found.items() if not _is_profile(s)]

    slug = slugify(kw)
    outdir = os.path.join(OUTBASE, slug)
    os.makedirs(outdir, exist_ok=True)
    # 기존 파일 정리(재수집 시 갱신)
    for f in os.listdir(outdir):
        if f.endswith((".jpg", ".png")):
            try:
                os.remove(os.path.join(outdir, f))
            except Exception:
                pass
    seen_hash = set()
    images = []
    for s, origin in srcs:
        if len(images) >= MAX_PER:
            break
        try:
            code, data = _dl(s)
        except Exception:
            continue
        if code != 200 or len(data) < 800:
            continue
        h = hashlib.md5(data).hexdigest()
        if h in seen_hash:            # 같은 크리에이티브 중복 제거
            continue
        seen_hash.add(h)
        ext = "png" if data[:4] == b"\x89PNG" else "jpg"
        fn = "%02d.%s" % (len(images) + 1, ext)
        fpath = os.path.join(outdir, fn)
        with open(fpath, "wb") as f:
            f.write(data)
        text = _ocr(fpath)                 # 소재 내 텍스트(OCR)
        w, h2 = _dims(fpath)
        # 소재 형식 판정: video poster 에서 왔거나 9:16 세로면 '영상'(릴스/스토리),
        # 그 외(정사각·4:5·가로 등 img 출처)는 '이미지' 소재로 본다.
        kind = "video" if (origin == "vid" or (h2 and w / h2 < 0.72)) else "image"
        images.append({"u": "comp-ads/%s/%s" % (slug, fn),
                       "t": text, "type": kind, "w": w, "h": h2})
        time.sleep(0.1)
    return {"kw": kw, "slug": slug, "count": len(images), "images": images,
            "at": time.strftime("%Y-%m-%d %H:%M")}


def main():
    kws = [k.strip() for k in (os.environ.get("CAPTURE_KW") or "").split(",") if k.strip()]
    if not kws and len(sys.argv) > 1:
        kws = [sys.argv[1]]
    if not kws:
        print("no keywords"); return
    os.makedirs(OUTBASE, exist_ok=True)
    mpath = os.path.join(OUTBASE, "manifest.json")
    try:
        manifest = json.load(io.open(mpath, encoding="utf-8"))
    except Exception:
        manifest = {}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=[
            "--no-sandbox", "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage"])
        ctx = browser.new_context(locale="ko-KR", user_agent=UA,
                                  viewport={"width": 1440, "height": 1000})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        for kw in kws:
            try:
                entry = capture_one(page, kw)
            except Exception as e:
                entry = {"kw": kw, "slug": slugify(kw), "count": 0, "images": [],
                         "at": time.strftime("%Y-%m-%d %H:%M"), "err": str(e)[:80]}
            manifest[entry["slug"]] = entry
            print(json.dumps({k: entry[k] for k in ("kw", "count", "at")}, ensure_ascii=False))
        browser.close()

    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("manifest:", len(manifest), "brands")


if __name__ == "__main__":
    main()
