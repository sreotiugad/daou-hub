"""Daou Hub data.json 빌더 (하루 1회 실행).

    구글시트 RAW → 집계 → report
    네이버 키워드툴  → keyword
    → daou-universe/data.json 저장

환경변수(키)가 있으면 실데이터, 없으면 자동으로 샘플을 만든다.
그래서 키가 없어도 사이트는 데모로 돌고, 키를 넣으면 실데이터로 바뀐다.

실행:  cd pipeline && python build_data.py
"""
import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C
import sheet_source
import aggregate
import keywords_naver
import sample as S


def main():
    logs = []

    # 1) 광고 리포트: 시트 RAW → 집계 (없으면 샘플)
    rows = sheet_source.read_rows(logs)
    if rows:
        rep = aggregate.build_report(rows)
        live_report = True
    else:
        rep = S.build_sample_report()
        live_report = False
    logs.append(f"[report] {'LIVE(시트)' if live_report else 'SAMPLE'} · 세부브랜드 {len(rep['report']['subs'])}종")

    # 2) 키워드: 네이버 실검색량 (없으면 샘플)
    kw = keywords_naver.fetch_keywords(C.KEYWORDS, logs)
    live_keyword = bool(kw)
    if not kw:
        kw = {k: S.build_sample_keyword(k) for k in C.KEYWORDS}
    logs.append(f"[keyword] {'LIVE(네이버)' if live_keyword else 'SAMPLE'} · {len(kw)}개")

    data = {
        "source": "live" if live_report else "sample",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": rep["period"],
        "report": rep["report"],
        "keyword": kw,
        "meta": {
            "live_report": live_report,
            "live_keyword": live_keyword,
            "present_subs": rep.get("_present", []),
        },
    }

    os.makedirs(os.path.dirname(C.OUT_PATH), exist_ok=True)
    with open(C.OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print("=== Daou Hub data.json ===")
    for l in logs:
        print(" ", l)
    print(f"  → wrote {C.OUT_PATH}  (source={data['source']})")


if __name__ == "__main__":
    main()
