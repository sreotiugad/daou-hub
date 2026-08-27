"""광고 API → RAW 자동 적재 (하루 1회).

    네이버/구글 광고 API  →  표준 행  →  raw/<source>-<date>.csv 누적

사용:
  python ingest.py                # 어제(KST) 하루 수집
  python ingest.py --date 2026-08-25
  python ingest.py --backfill 7   # 최근 7일
  python ingest.py --sample       # 키 없이 배선 검증용 더미 RAW 생성

계정/사업규칙은 accounts.json(또는 env DAOU_AD_ACCOUNTS)에서 읽는다.
계정이 없으면 아무것도 안 쓴다(기존 data.json 유지).
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C
import ad_config
import raw_store
import bq_store
import ingest_naver_ads as NAVER
import ingest_google_ads as GOOGLE


def _sink(source, date_iso, rows, logs):
    """수집 결과를 창고에 적재: 빅쿼리 설정돼 있으면 BQ, 아니면 raw/ 폴더."""
    if not rows:
        return
    if bq_store.enabled():
        if bq_store.write_day(source, date_iso, rows, logs):
            return
    raw_store.write_day(source, date_iso, rows, logs)


def _kst_yesterday():
    kst = datetime.now(timezone.utc) + timedelta(hours=9)
    return (kst.date() - timedelta(days=1)).isoformat()


def _dates(args):
    if args.date:
        return [args.date]
    end = _kst_yesterday()
    n = max(1, args.backfill)
    y, m, d = map(int, end.split("-"))
    from datetime import date as _d
    e = _d(y, m, d)
    return [(e - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _sample_rows(date_iso):
    """키 없이 파이프라인 배선만 검증하는 더미 RAW."""
    import random
    rnd = random.Random(date_iso)
    combos = [("네이버", "파워링크"), ("네이버", "브랜드검색"), ("구글", "구글검색"), ("구글", "실적최대화")]
    rows = []
    for svc in C.BRAND_MAP:
        for media, ct in combos:
            net = rnd.randint(20000, 900000)
            clk = max(1, int(net / rnd.randint(400, 800)))
            imp = int(clk / (0.02 + rnd.random() * 0.04))
            rows.append({
                "서비스": svc, "매체": media, "캠페인 유형": ct,
                "캠페인": f"{svc} {ct} 캠페인", "기간": date_iso,
                "노출 수": imp, "클릭 수": clk, "총 비용": net,
                "가입": round(clk / rnd.randint(8, 30), 1),
                "광고비(마크업포함,VAT포함)": ad_config.marked_cost(net, media, 0.0, 0.10),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", type=int, default=1)
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    logs = []
    dates = _dates(args)

    if args.sample:
        for d in dates:
            _sink("sample", d, _sample_rows(d), logs)
        _print(logs)
        return

    cfg = ad_config.load(logs)
    defaults = cfg.get("defaults", {})
    n_acc, g_acc = cfg.get("naver", []), cfg.get("google", [])
    if not n_acc and not g_acc:
        _print(logs)
        print("  계정 설정이 없어 수집을 건너뜁니다. (--sample 로 배선 검증 가능)")
        return

    for d in dates:
        nrows = []
        for acc in n_acc:
            nrows += NAVER.fetch_day(acc, d, defaults, logs)
        _sink("naver", d, nrows, logs)
        grows = []
        for acc in g_acc:
            grows += GOOGLE.fetch_day(acc, d, defaults, logs)
        _sink("google", d, grows, logs)
    _print(logs)


def _print(logs):
    print("=== Daou Hub ingest ===")
    for l in logs:
        print(" ", l)


if __name__ == "__main__":
    main()
