"""RAW 저장소 (repo의 raw/ 폴더).

Vercel 서버를 쓰지 않는 정적 구조에서 '누적 RAW'를 두는 곳.
구글시트/빅쿼리 대신 GitHub 저장소 안 raw/ 폴더에 날짜별 CSV로 쌓는다.
  - 광고 API 수집 결과(ingest.py) → raw/<source>-<YYYY-MM-DD>.csv  (같은 날 재실행 시 덮어씀 = idempotent)
  - aggregate 는 raw/*.csv 를 전부 읽어 집계

CSV 헤더는 ADEF 데일리 리포트 'raw' 시트와 동일 → sheet_source.records_to_rows 를 그대로 재사용.
"""
import os
import csv
import glob
import config as C
import sheet_source

RAW_DIR = os.path.join(C.REPO_ROOT, "raw")

# 표준 헤더(= ADEF raw 시트 헤더). 순서 고정.
HEADERS = ["서비스", "매체", "캠페인 유형", "캠페인", "기간",
           "노출 수", "클릭 수", "총 비용", "가입", "광고비(마크업포함,VAT포함)"]


def _path(source, date_iso):
    return os.path.join(RAW_DIR, f"{source}-{date_iso}.csv")


def write_day(source, date_iso, rows, logs=None):
    """하루치 수집 결과를 raw/<source>-<date>.csv 로 저장(덮어씀).
    rows: HEADERS 를 키로 갖는 dict 리스트."""
    logs = logs if logs is not None else []
    os.makedirs(RAW_DIR, exist_ok=True)
    p = _path(source, date_iso)
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in HEADERS})
    logs.append(f"[raw] wrote {os.path.relpath(p, C.REPO_ROOT)} · {len(rows)}행")
    return p


def has_data():
    return bool(glob.glob(os.path.join(RAW_DIR, "*.csv")))


def read_rows(logs=None):
    """raw/*.csv 를 전부 읽어 표준 행 리스트로. 없으면 빈 리스트."""
    logs = logs if logs is not None else []
    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    if not files:
        logs.append("[raw] raw/ 비어있음")
        return []
    records = []
    for fp in files:
        with open(fp, "r", encoding="utf-8-sig") as f:
            records.extend(list(csv.DictReader(f)))
    logs.append(f"[raw] {len(files)}개 파일 · {len(records)}행")
    return sheet_source.records_to_rows(records, logs)
