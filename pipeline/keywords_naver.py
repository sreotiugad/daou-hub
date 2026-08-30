"""네이버 검색광고 키워드툴(/keywordstool)로 실검색량·경쟁정도·연관키워드를 가져온다.

인증: adcon_report.py 와 동일한 HMAC 서명 방식.
필요 환경변수: NAVER1_CUSTOMER_ID / NAVER1_API_KEY / NAVER1_SECRET_KEY

키워드툴이 주는 것(실데이터): 월 PC/모바일 검색수, 경쟁정도(compIdx),
평균 광고노출개수(plAvgDepth), 연관키워드.
키워드툴이 주지 않는 것(모델 추정으로 보완): 성별·연령·요일·시간대 분포,
12개월 추이, 콘텐츠 발행량, 광고 경쟁 브랜드 → sample.model_extras 사용.
CPC 는 키워드툴 미제공 → 경쟁정도 기반 추정.
"""
import time
import hmac
import hashlib
import base64
import requests
import config as C
import sample as S
import providers_youtube as YT
import providers_naver_extra as NX

BASE = "https://api.searchad.naver.com"


def _headers(acc, uri, method="GET"):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}.{method}.{uri}"
    sig = base64.b64encode(
        hmac.new(str(acc["secret_key"]).encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    return {"X-Timestamp": ts, "X-API-KEY": str(acc["api_key"]),
            "X-Customer": str(acc["customer_id"]), "X-Signature": sig,
            "Content-Type": "application/json"}


def _int(v):
    s = str(v).strip()
    if "<" in s:      # "< 10"
        return 9
    try:
        return int(float(s.replace(",", "")))
    except Exception:
        return 0


def _est_cpc(level):
    return {"낮음": 550, "중간": 1100, "높음": 1650}.get(level, 900)


def _attach_related_docs(related, logs):
    """연관키워드 8개의 문서수를 실제 네이버 검색 문서수(블로그+카페)로 채운다.
    상위 8개만·병렬로 조회해 쿼터/지연을 줄이고, 실패분은 프론트 추정값을 유지한다.
    개발자 키(NAVER_DEV_*) 없으면 아무것도 안 하고 프론트 추정 유지."""
    if not related or not (NX.DEV_ID() and NX.DEV_SECRET()):
        return
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        try:
            dc = NX.content_count(item["kw"], [])  # 로그는 버림(스레드·과다로그 방지)
            if dc is not None:
                item["doc"] = dc
        except Exception:
            pass

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(one, related))
        n = sum(1 for r in related if "doc" in r)
        logs.append(f"[search] 연관키워드 문서수 {n}/{len(related)}건 실데이터")
    except Exception as e:
        logs.append(f"[search] 연관 문서수 오류: {str(e)[:80]}")


def fetch_keyword(kw, acc, logs=None):
    """한 키워드 분석. 실패하면 None."""
    logs = logs if logs is not None else []
    uri = "/keywordstool"
    params = {"hintKeywords": kw.replace(" ", ""), "showDetail": "1"}
    try:
        r = requests.get(BASE + uri, params=params, headers=_headers(acc, uri), timeout=15)
        if r.status_code != 200:
            logs.append(f"[kw] {kw} status={r.status_code}")
            return None
        rows = r.json().get("keywordList", []) or []
    except Exception as e:
        logs.append(f"[kw] {kw} 오류: {e}")
        return None
    if not rows:
        return None

    norm = kw.replace(" ", "")
    head = next((x for x in rows if str(x.get("relKeyword", "")).replace(" ", "") == norm), rows[0])
    pc = _int(head.get("monthlyPcQcCnt"))
    mob = _int(head.get("monthlyMobileQcCnt"))
    total = pc + mob
    if total <= 0:
        total = 10
    m_share = (mob / total) if total else .7
    level = str(head.get("compIdx", "중간")).strip() or "중간"
    if level not in ("낮음", "중간", "높음"):
        level = "중간"
    advertisers = _int(head.get("plAvgDepth")) or (2 if level == "낮음" else 6 if level == "중간" else 11)
    cpc = _est_cpc(level)

    related = []
    for x in rows:
        rk = str(x.get("relKeyword", "")).replace(" ", "")
        if rk == norm:
            continue
        rp = _int(x.get("monthlyPcQcCnt")) + _int(x.get("monthlyMobileQcCnt"))
        lv = str(x.get("compIdx", "중간")).strip()
        if lv not in ("낮음", "중간", "높음"):
            lv = "중간"
        related.append({"kw": str(x.get("relKeyword", "")).strip(), "v": rp,
                        "comp": lv, "cpc": _est_cpc(lv)})
    # 네이버가 준 '전체' 후보를 검색량순 정렬 후 top 8 (예전엔 앞 12개만 보고 정렬해
    # 진짜 상위 키워드가 잘리는 버그가 있었음).
    related.sort(key=lambda z: -z["v"])
    related = related[:8]
    ex = S.model_extras(kw, total, m_share)

    # ── 실데이터 보강 ── 독립적인 소스들을 '동시에' 호출한다.
    # 전에는 하나씩 순차 호출(전체 = 합)이라 느렸음 → 병렬(전체 = 가장 느린 하나).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_ecpc = pool.submit(NX.estimate_cpc, kw, acc, logs)          # 예상 입찰가
        f_cc = pool.submit(NX.content_count, kw, logs)               # 콘텐츠 문서수
        f_dl = pool.submit(NX.datalab, kw, total, m_share, logs)     # 추이·성별·연령
        f_yt = pool.submit(YT.fetch_videos, kw, 8, logs)            # 유튜브 영상
        f_rdoc = pool.submit(_attach_related_docs, related, logs)    # 연관 문서수(내부 병렬)
        f_rcpc = pool.submit(NX.estimate_cpc_batch,
                             [z["kw"] for z in related], acc, logs)  # 연관 CPC(배치)

        def _get(f, default):
            try:
                return f.result()
            except Exception:
                return default
        ecpc = _get(f_ecpc, None)
        cc = _get(f_cc, None)
        dl = _get(f_dl, None) or {}
        yt = _get(f_yt, None)
        _get(f_rdoc, None)                    # related 에 doc 채움(부작용)
        rbids = _get(f_rcpc, {}) or {}

    if ecpc:
        cpc = ecpc
    # 연관키워드 CPC 실값 적용(실패분은 경쟁도 추정 유지)
    for z in related:
        b = rbids.get(z["kw"].replace(" ", ""))
        if b:
            z["cpc"] = b

    blog = cc if cc is not None else ex["blog"]
    sat = round(blog / total, 1) if total else 0
    trend = dl.get("trend", ex["trend"])
    male = dl.get("male", ex["male"])
    female = dl.get("female", ex["female"])
    age = dl.get("age", ex["age"])
    youtube = yt if yt is not None else S.model_youtube(kw)

    for b in ex["brands"]:
        b["bid"] = cpc if b["us"] else round(cpc * 0.9)

    return {"total": total, "pc": pc, "mob": mob, "mShare": round(m_share, 4),
            "advertisers": advertisers, "comp": level, "cpc": cpc,
            "blog": blog, "sat": sat, "trend": trend,
            "male": male, "female": female, "age": age,
            "dow": ex["dow"], "hourP": ex["hourP"], "related": related,
            "brands": ex["brands"], "youtube": youtube}


def fetch_keywords(keywords, logs=None):
    """설정된 키워드 목록을 실검색량으로. 계정 없으면 빈 딕셔너리."""
    logs = logs if logs is not None else []
    acc = C.naver_account()
    if not acc:
        logs.append("[kw] NAVER 계정 없음 → 키워드 실검색량 스킵")
        return {}
    out = {}
    for kw in keywords:
        d = fetch_keyword(kw, acc, logs)
        if d:
            out[kw] = d
        time.sleep(0.3)  # 레이트리밋 여유
    logs.append(f"[kw] 실검색량 {len(out)}/{len(keywords)}개")
    return out
