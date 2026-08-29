"""BigQuery RAW 창고.

매일 수집한 광고 raw 를 BigQuery 테이블에 누적한다(durable). aggregate 는
여기서 읽어 data.json 을 만든다. Vercel 은 여전히 정적 파일만 서빙.

왜 BigQuery: 브랜드/소스가 늘고 키워드까지 누적하면 스프레드시트보다
테이블 분리·확장·질의가 깔끔하고, 무료 티어로 충분하다.

환경변수:
  BQ_DATASET                  데이터셋 이름 (예: daou_hub) — 있으면 BQ 사용
  BQ_ADS_TABLE                광고 raw 테이블 (기본 ads_raw)
  BQ_PROJECT                  (선택) 프로젝트 ID. 없으면 서비스계정 JSON 의 project_id
  GA4_SERVICE_ACCOUNT_JSON    서비스계정 (BigQuery Data Editor + Job User 권한 필요)

설정 없거나 라이브러리 없으면 enabled()=False → 파이프라인은 raw/ 폴더로 폴백.

테이블 스키마(ads_raw):
  date DATE, service STRING, media STRING, camptype STRING, campaign STRING,
  imp INT64, click INT64, cost_net INT64, signup FLOAT64, cost_marked INT64,
  source STRING, ingested_at TIMESTAMP
"""
import os
from datetime import datetime, timezone
import config as C

_SCHEMA = [
    ("date", "DATE"), ("service", "STRING"), ("media", "STRING"),
    ("camptype", "STRING"), ("campaign", "STRING"), ("imp", "INT64"),
    ("click", "INT64"), ("cost_net", "INT64"), ("signup", "FLOAT64"),
    ("cost_marked", "INT64"), ("source", "STRING"), ("ingested_at", "TIMESTAMP"),
]

# raw_store.HEADERS(한글) → BQ 컬럼
_H2C = {
    "서비스": "service", "매체": "media", "캠페인 유형": "camptype",
    "캠페인": "campaign", "기간": "date", "노출 수": "imp", "클릭 수": "click",
    "총 비용": "cost_net", "가입": "signup", "광고비(마크업포함,VAT포함)": "cost_marked",
}


def _dataset():
    return os.environ.get("BQ_DATASET", "").strip()


def enabled():
    return bool(_dataset() and C.service_account_info())


def _client(logs):
    try:
        from google.cloud import bigquery
        from google.oauth2.service_account import Credentials
    except Exception as e:
        logs.append(f"[bq] 라이브러리 미설치: {e}")
        return None, None
    info = C.service_account_info()
    creds = Credentials.from_service_account_info(info)
    project = os.environ.get("BQ_PROJECT") or info.get("project_id")
    return bigquery.Client(project=project, credentials=creds), bigquery


def _table_id(bq_client):
    # 미설정 시크릿은 빈 문자열로 들어올 수 있으므로 or 로 기본값 보장
    tbl = (os.environ.get("BQ_ADS_TABLE") or "ads_raw").strip()
    return f"{bq_client.project}.{_dataset()}.{tbl}"


def _ensure(bq_client, bigquery, logs):
    ds_id = f"{bq_client.project}.{_dataset()}"
    try:
        bq_client.get_dataset(ds_id)
    except Exception:
        bq_client.create_dataset(bigquery.Dataset(ds_id), exists_ok=True)
        logs.append(f"[bq] dataset 생성 {ds_id}")
    tid = _table_id(bq_client)
    try:
        bq_client.get_table(tid)
    except Exception:
        schema = [bigquery.SchemaField(n, t) for n, t in _SCHEMA]
        bq_client.create_table(bigquery.Table(tid, schema=schema), exists_ok=True)
        logs.append(f"[bq] table 생성 {tid}")
    return tid


def write_day(source, date_iso, rows, logs=None):
    """하루치를 테이블에 적재. 같은 (date,source) 는 지우고 다시 넣어 idempotent."""
    logs = logs if logs is not None else []
    if not enabled():
        return False
    bq_client, bigquery = _client(logs)
    if bq_client is None:
        return False
    tid = _ensure(bq_client, bigquery, logs)
    # 멱등: 같은 날짜+소스 삭제 후 삽입
    bq_client.query(
        f"DELETE FROM `{tid}` WHERE date=@d AND source=@s",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("d", "DATE", date_iso),
            bigquery.ScalarQueryParameter("s", "STRING", source),
        ]),
    ).result()
    now = datetime.now(timezone.utc).isoformat()
    payload = []
    for r in rows:
        rec = {c: r.get(h) for h, c in _H2C.items()}
        rec["source"] = source
        rec["ingested_at"] = now
        payload.append(rec)
    if payload:
        errs = bq_client.insert_rows_json(tid, payload)
        if errs:
            logs.append(f"[bq] insert 오류: {errs[:2]}")
            return False
    logs.append(f"[bq] {source} {date_iso} · {len(payload)}행 적재")
    return True


def read_rows(logs=None):
    """테이블 전체를 표준 행(service/media/camptype/date/imp/click/cost/signup)으로."""
    logs = logs if logs is not None else []
    if not enabled():
        return []
    bq_client, bigquery = _client(logs)
    if bq_client is None:
        return []
    tid = _table_id(bq_client)
    try:
        it = bq_client.query(
            f"SELECT date, service, media, camptype, imp, click, cost_marked, signup "
            f"FROM `{tid}` WHERE source != 'sample'"
        ).result()
    except Exception as e:
        logs.append(f"[bq] read 오류(테이블 없음?): {e}")
        return []
    out = []
    for r in it:
        svc = str(r["service"] or "").strip()
        if svc not in C.BRAND_MAP:
            continue
        media = C.norm_media(r["media"])
        out.append({
            "service": svc,
            "media": media,
            "camptype": C.norm_ct(r["camptype"], media),
            "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"])[:10],
            "imp": float(r["imp"] or 0),
            "click": float(r["click"] or 0),
            "cost": float(r["cost_marked"] or 0),
            "signup": float(r["signup"] or 0),
        })
    logs.append(f"[bq] {len(out)}행 읽음")
    return out
