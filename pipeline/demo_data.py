"""제출·데모용 합성 data.json 생성기 (재현 가능).

⚠️ 왜 필요한가
    이전 합성 데이터는 '매체'와 '캠페인유형'을 서로 독립으로 뽑아 곱했다.
    그 결과 `구글 × 파워링크`, `메타 × 구글검색` 처럼 실제로 존재할 수 없는
    조합이 61% 생겨, 광고 실무자가 보면 바로 가짜인 게 드러났다.

    이 생성기는 매체별로 '그 매체가 실제로 파는 상품'만 뽑는다(joint 분포).
        네이버 → 파워링크 · 브랜드검색 · 쇼핑검색
        구글   → 구글검색 · 실적최대화 · GDN · 동영상
        메타   → 디스플레이
    캠페인명 접두사(NV/GG/MT)도 매체와 일치시키고, 네이버 검색과 구글검색에는
    광고그룹과 평균노출순위를 채워 실제 RAW와 같은 입도를 갖게 한다.

실행:  cd pipeline && python demo_data.py      (repo 루트 data.json 을 덮어씀)
실데이터로 복귀: .github/workflows/daily-data.yml 의 schedule 주석 해제 후 mode=real 실행.
"""
import os, json, math, random
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data.json")
DAYS = 365
SEED = 20260910

# 매체가 실제로 파는 캠페인유형만 — 이 표 밖의 조합은 만들지 않는다.
MEDIA_CT = {
    "네이버": ["파워링크", "브랜드검색", "쇼핑검색"],
    "구글":   ["구글검색", "실적최대화", "GDN", "동영상"],
    "메타":   ["디스플레이"],
}
PFX = {"네이버": "NV", "구글": "GG", "메타": "MT"}
# 광고그룹·노출순위를 갖는 유형(네이버 검색 + 구글검색) — 실제 RAW와 동일한 입도
ADG_CT = {"파워링크", "브랜드검색", "쇼핑검색", "구글검색"}
RANK_CT = {"파워링크", "브랜드검색", "쇼핑검색"}          # 평균노출순위는 네이버 검색 지표

# 유형별 클릭단가·클릭률 범위 (cpc원, ctr)
CT_PERF = {
    "브랜드검색": ((140, 240),  (.075, .115)),
    "파워링크":   ((480, 900),  (.030, .052)),
    "쇼핑검색":   ((280, 520),  (.012, .022)),
    "구글검색":   ((520, 980),  (.042, .068)),
    "실적최대화": ((320, 620),  (.008, .016)),
    "GDN":       ((90, 210),   (.0035, .0075)),
    "동영상":     ((60, 150),   (.0035, .0080)),
    "디스플레이": ((240, 520),  (.009, .018)),
}
# 유형별 CPA 배수 — 브랜드검색은 싸게 먹히고 GDN·동영상은 비싸다(인지 목적).
# 서비스 단위 CPA가 목표값에 정확히 맞도록 아래에서 정규화한다.
CT_CPA_MULT = {
    "브랜드검색": .55, "파워링크": .95, "쇼핑검색": 1.20, "구글검색": 1.00,
    "실적최대화": 1.15, "GDN": 2.30, "동영상": 2.80, "디스플레이": 1.70,
}
# 매체 안에서의 유형 비중(기본값) — 서비스별로 약간씩 흔들어 쓴다.
CT_MIX = {
    "네이버": {"파워링크": .58, "브랜드검색": .22, "쇼핑검색": .20},
    "구글":   {"구글검색": .44, "실적최대화": .26, "GDN": .20, "동영상": .10},
    "메타":   {"디스플레이": 1.0},
}
BRANDS = {
    "사방넷":     ["사방넷", "사방넷미니", "풀필먼트"],
    "뿌리오":     ["뿌리오", "반값문자", "알뜰문자", "문자매니아"],
    "다우오피스": ["다우오피스", "다우오피스HR"],
    "애드콘":     ["애드콘", "엔팩스"],
    "애드웰":     ["애드웰"],
}
# 서비스별 (월 광고비 원, 목표 CPA 원) — 실제 운영 규모 기준.
#   ※ 뿌리오 계열·엔팩스·애드웰 CPA 는 추정값(운영자 확인 필요).
SVC_PLAN = {
    "사방넷":       (80_000_000, 300_000),
    "사방넷미니":   (20_000_000, 240_000),
    "풀필먼트":     (14_000_000, 380_000),
    "뿌리오":       (36_000_000,  30_000),
    "반값문자":     (20_000_000,  25_000),
    "알뜰문자":     (16_000_000,  28_000),
    "문자매니아":   ( 8_000_000,  35_000),
    "다우오피스":   (60_000_000, 300_000),
    "다우오피스HR": (20_000_000, 360_000),
    "애드콘":       (20_000_000,   8_000),
    "엔팩스":       ( 1_200_000,  60_000),
    "애드웰":       (10_000_000, 150_000),
}
# 서비스별 매체 비중 · 월추세(mo: +면 우상향)
SVC_MEDIA = {
    "사방넷": ({"네이버": .55, "구글": .33, "메타": .12}, .35),
    "사방넷미니": ({"네이버": .60, "구글": .28, "메타": .12}, .55),
    "풀필먼트": ({"네이버": .50, "구글": .40, "메타": .10}, -.20),
    "뿌리오": ({"네이버": .65, "구글": .25, "메타": .10}, .20),
    "반값문자": ({"네이버": .70, "구글": .22, "메타": .08}, .30),
    "알뜰문자": ({"네이버": .68, "구글": .24, "메타": .08}, .10),
    "문자매니아": ({"네이버": .66, "구글": .26, "메타": .08}, -.15),
    "다우오피스": ({"네이버": .52, "구글": .38, "메타": .10}, .25),
    "다우오피스HR": ({"네이버": .48, "구글": .40, "메타": .12}, -.30),
    "애드콘": ({"네이버": .50, "구글": .35, "메타": .15}, .45),
    "엔팩스": ({"네이버": .62, "구글": .30, "메타": .08}, .05),
    "애드웰": ({"네이버": .40, "구글": .45, "메타": .15}, .30),
}
ADG_WORDS = ["일반", "브랜드", "경쟁사", "프로모션", "롱테일"]


def main():
    rnd = random.Random(SEED)
    end = date(2026, 9, 9)
    dates = [(end - timedelta(days=DAYS - 1 - i)).isoformat() for i in range(DAYS)]

    # 1) 캠페인 설계: (서비스, 매체, 유형) → 캠페인 1개(+광고그룹 몇 개)
    #    월예산을 매체→유형으로 쪼개고, 목표 CPA 는 유형별 배수로 배분한다.
    #    배수를 그대로 쓰면 서비스 CPA 가 목표에서 밀리므로 조화평균으로 정규화(scale)해
    #    서비스 단위 CPA 가 목표값에 정확히 수렴하게 만든다.
    plan = []
    seq = 0
    for grp, subs in BRANDS.items():
        for svc in subs:
            monthly, cpa_target = SVC_PLAN[svc]
            # /0.945 = 주말 감소(2/7일 ×0.86)로 평균이 낮아지는 만큼 보정 → 월예산이 목표에 맞음
            daily_total = monthly * 12.0 / DAYS / 0.945
            mmix, mo = SVC_MEDIA[svc]
            combos = []                     # (media, ct, daily, mult)
            for media, mshare in mmix.items():
                mix = {k: v * (0.8 + 0.4 * rnd.random()) for k, v in CT_MIX[media].items()}
                tot = sum(mix.values())
                for ct, cshare in mix.items():
                    daily = daily_total * mshare * (cshare / tot)
                    if daily < 600:         # 너무 작은 조합은 아예 집행 안 한 것으로
                        continue
                    combos.append((media, ct, daily, CT_CPA_MULT[ct]))
            spend = sum(c[2] for c in combos) or 1.0
            # scale = 1/Σ(share/mult) 의 역수 관계 → signup_i = cost_i/(CPA·mult_i·scale)
            scale = sum((c[2] / spend) / c[3] for c in combos) or 1.0
            for media, ct, daily, mult in combos:
                seq += 1
                cpcR, ctrR = CT_PERF[ct]
                U = lambda a, b: a + (b - a) * rnd.random()
                adgs = []
                if ct in ADG_CT:
                    n = 2 if ct in ("파워링크", "구글검색") else 1   # 주력 검색만 광고그룹 2개
                    for w in rnd.sample(ADG_WORDS, n):
                        adgs.append("%s_%s_%s" % (svc, rnd.choice(["PC", "MO"]), w))
                plan.append(dict(
                    svc=svc, grp=grp, media=media, ct=ct,
                    cmp="%s_%s_%s_%02d" % (PFX[media], svc, ct, seq),
                    adgs=adgs or [""], daily=daily, mo=mo,
                    cpc=U(*cpcR), ctr=U(*ctrR),
                    cpa=cpa_target * mult * scale,      # 이 캠페인의 목표 CPA
                    # 유튜브(동영상)는 캠페인성 구간 집행, GDN은 리타게팅으로 상시 집행
                    burst=(ct == "동영상"),
                    seed=rnd.random(),
                ))

    # 2) 일자별 팩트 생성
    facts = []
    for p in plan:
        r2 = random.Random(hash(p["cmp"]) & 0xFFFFFFFF)
        # 구간 집행 캠페인은 연중 2~3개 구간에서만 노출
        windows = []
        if p["burst"]:
            for _ in range(r2.choice([2, 3])):
                s = r2.randrange(0, DAYS - 40)
                windows.append((s, s + r2.randrange(25, 55)))
        nadg = len(p["adgs"])
        for i, d in enumerate(dates):
            if p["burst"] and not any(a <= i < b for a, b in windows):
                continue
            t = i / (DAYS - 1)
            trend = 1 + p["mo"] * (t - .5) * .5                  # 완만한 우상향/하락
            dow = (date.fromisoformat(d).weekday())
            wk = .86 if dow >= 5 else 1.0                        # 주말 감소
            seas = 1 + .06 * math.sin(t * 6.283 * 2 + p["seed"] * 6.283)
            noise = .86 + .28 * r2.random()
            cost_day = p["daily"] * trend * wk * seas * noise
            if cost_day < 500:
                continue
            # 최근 30일은 효율이 소폭 개선(증감 지표가 의미 있게 보이도록) → CPA 하락
            cpa = p["cpa"] * (0.92 if i >= DAYS - 30 else 1.0) * (.90 + .20 * r2.random())
            for j, adg in enumerate(p["adgs"]):
                w = (1.0 / nadg) * (0.75 + 0.5 * r2.random()) if nadg > 1 else 1.0
                cost = cost_day * w
                if cost < 300:
                    continue
                click = cost / p["cpc"]
                imp = click / p["ctr"]
                signup = cost / cpa
                f = {"d": d, "svc": p["svc"], "grp": p["grp"], "media": p["media"],
                     "ct": p["ct"], "cmp": p["cmp"], "adg": adg, "ad": "",
                     "imp": int(round(imp)), "click": int(round(click)),
                     "cost": int(round(cost)), "signup": round(signup, 1),
                     "rnkw": 0, "rnki": 0}
                if p["ct"] in RANK_CT:
                    rank = 1.1 + 2.5 * r2.random()
                    f["rnkw"] = int(round(rank * f["imp"]))
                    f["rnki"] = f["imp"]
                facts.append(f)
    facts.sort(key=lambda f: (f["d"], f["grp"], f["svc"], f["media"], f["ct"], f["cmp"], f["adg"]))

    # 3) 서비스별 일자 배열(subs) — 팩트에서 역산해 항상 일치하게
    idx = {d: i for i, d in enumerate(dates)}
    subs, mset, ctset = {}, {}, {}
    for f in facts:
        s = subs.setdefault(f["svc"], {"group": f["grp"],
                                       "cost": [0] * DAYS, "signup": [0] * DAYS,
                                       "imp": [0] * DAYS, "click": [0] * DAYS})
        i = idx[f["d"]]
        s["cost"][i] += f["cost"]; s["signup"][i] += f["signup"]
        s["imp"][i] += f["imp"];   s["click"][i] += f["click"]
        mset.setdefault(f["svc"], {}).setdefault(f["media"], 0)
        mset[f["svc"]][f["media"]] += f["cost"]
        ctset.setdefault(f["svc"], {}).setdefault(f["ct"], 0)
        ctset[f["svc"]][f["ct"]] += f["cost"]
    for svc, s in subs.items():
        s["signup"] = [round(v, 1) for v in s["signup"]]
        tm = sum(mset[svc].values()) or 1
        s["media"] = {k: round(v / tm, 4) for k, v in sorted(mset[svc].items(), key=lambda x: -x[1])}
        tc = sum(ctset[svc].values()) or 1
        s["ct"] = {k: round(v / tc, 4) for k, v in sorted(ctset[svc].items(), key=lambda x: -x[1])}

    brands = {g: {"subs": [n for n in sl if n in subs]} for g, sl in BRANDS.items()}

    old = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    out = {
        "source": "sample",
        "generated_at": date.today().isoformat(),
        "period": {"start": dates[0], "end": dates[-1], "days": DAYS, "dates": dates},
        "report": {"brands": brands, "subs": subs, "facts": facts},
        "keyword": old.get("keyword", {}),
        "meta": {"live_report": False, "live_keyword": False,
                 "present_subs": list(subs.keys()),
                 "note": "제출·데모용 합성 데이터 (pipeline/demo_data.py 로 생성). 매체별 실제 상품 조합만 사용."},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("facts=%d · 서비스=%d · %.1fMB" % (len(facts), len(subs), os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
