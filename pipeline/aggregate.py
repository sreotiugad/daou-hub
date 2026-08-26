"""표준 행 리스트 → 프론트(app.html)가 읽는 report 구조로 집계.

출력:
  {
    "period": {"start","end","days","dates":[ISO...]},
    "report": {
      "brands": {group: {"subs":[...]}},
      "subs": {
        sub: {"group", "cost":[..N], "signup":[..N], "imp":[..N], "click":[..N],
              "media":{"네이버":frac,"구글":frac}, "ct":{ct:frac,...}}
      }
    }
  }
"""
from datetime import date, timedelta
import config as C


def _date_axis(rows, days):
    """RAW 최신 날짜를 끝으로 최근 `days`일 축을 만든다. 행이 없으면 어제 기준."""
    dates = sorted({r["date"] for r in rows if r["date"]})
    end = dates[-1] if dates else (date.today() - timedelta(days=1)).isoformat()
    y, m, d = map(int, end.split("-"))
    end_d = date(y, m, d)
    axis = [(end_d - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return axis


def build_report(rows, days=None):
    days = days or C.PERIOD_DAYS
    axis = _date_axis(rows, days)
    idx = {d: i for i, d in enumerate(axis)}

    subs = {}
    def blank(sub):
        return {
            "group": C.BRAND_MAP[sub][0],
            "cost": [0.0] * days, "signup": [0.0] * days,
            "imp": [0.0] * days, "click": [0.0] * days,
            "_media": {"네이버": 0.0, "구글": 0.0},
            "_ct": {k: 0.0 for k in C.CT_ORDER},
        }

    # 시트에 존재하는 세부브랜드만 채운다
    present = set()
    for r in rows:
        sub = r["service"]
        if sub not in C.BRAND_MAP:
            continue
        i = idx.get(r["date"])
        if i is None:
            continue
        present.add(sub)
        s = subs.setdefault(sub, blank(sub))
        s["cost"][i] += r["cost"]
        s["signup"][i] += r["signup"]
        s["imp"][i] += r["imp"]
        s["click"][i] += r["click"]
        s["_media"][r["media"]] = s["_media"].get(r["media"], 0.0) + r["cost"]
        s["_ct"][r["camptype"]] = s["_ct"].get(r["camptype"], 0.0) + r["cost"]

    # 비율로 정규화 + 라운딩
    out_subs = {}
    for sub, s in subs.items():
        tot = sum(s["cost"]) or 1.0
        media = {k: round(v / tot, 4) for k, v in s["_media"].items()}
        if not media:
            media = {"네이버": 0.6, "구글": 0.4}
        ctsum = sum(s["_ct"].values()) or 1.0
        ct = {k: round(v / ctsum, 4) for k, v in s["_ct"].items()}
        out_subs[sub] = {
            "group": s["group"],
            "cost": [round(x) for x in s["cost"]],
            "signup": [round(x, 1) for x in s["signup"]],
            "imp": [round(x) for x in s["imp"]],
            "click": [round(x) for x in s["click"]],
            "media": media,
            "ct": ct,
        }

    # brands: 시트에 데이터가 있는 세부브랜드만 노출(없으면 프론트 기본값 사용)
    brands = {}
    for g in C.GROUPS:
        gsubs = [s for s in C.GROUP_SUBS[g] if s in out_subs]
        if gsubs:
            brands[g] = {"subs": gsubs}

    return {
        "period": {"start": axis[0], "end": axis[-1], "days": days, "dates": axis},
        "report": {"brands": brands, "subs": out_subs},
        "_present": sorted(present),
    }
