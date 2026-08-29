"""구글시트 RAW 워크시트를 읽어 표준 행 리스트로 반환한다.

반환 행 스키마:
    {service, media, camptype, date(YYYY-MM-DD), imp, click, cost, signup}

필요 환경변수:
    DAOU_SHEET_ID              누적 RAW 스프레드시트 ID
    GA4_SERVICE_ACCOUNT_JSON   서비스계정 JSON (편집자로 시트 공유돼 있어야 함)
    (선택) DAOU_SHEET_WORKSHEET  워크시트 탭 이름 (기본 'RAW')
"""
from datetime import date, datetime
import config as C


def _num(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _iso_date(v):
    s = str(v or "").strip()
    if not s:
        return ""
    s = s.replace(".", "-").replace("/", "-")
    # YYYYMMDD
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date().isoformat()
        except Exception:
            continue
    # 이미 ISO 앞 10자
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return ""


def read_rows(logs=None):
    """시트에서 표준 행을 읽는다. 자격증명/시트가 없으면 빈 리스트."""
    logs = logs if logs is not None else []
    if not C.sheet_ready():
        logs.append("[sheet] DAOU_SHEET_ID/서비스계정 없음 → 시트 스킵")
        return []
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception as e:
        logs.append(f"[sheet] gspread/google-auth 미설치: {e}")
        return []

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(C.service_account_info(), scopes=scopes)
    gc = gspread.authorize(creds)

    records = []
    for sid in C.SHEET_IDS:
        try:
            sh = gc.open_by_key(sid)
        except Exception as e:
            logs.append(f"[sheet] {sid[:8]}… 열기 실패: {e}")
            continue
        ws = None
        try:
            ws = sh.worksheet(C.SHEET_WORKSHEET)
        except Exception:
            # 대소문자 무관하게 'raw' 탭 탐색
            for w in sh.worksheets():
                if str(w.title).strip().lower() == C.SHEET_WORKSHEET.strip().lower():
                    ws = w
                    break
        if ws is None:
            ws = sh.sheet1
            logs.append(f"[sheet] {sid[:8]}… '{C.SHEET_WORKSHEET}' 탭 없음 → 첫 시트")
        recs = ws.get_all_records()  # 첫 행을 헤더로
        logs.append(f"[sheet] {sid[:8]}… {len(recs)}행")
        records.extend(recs)

    return records_to_rows(records, logs)


def records_to_rows(records, logs=None):
    """헤더-값 dict 리스트(구글시트/엑셀 공통) → 표준 행. 알 수 없는 서비스는 스킵."""
    logs = logs if logs is not None else []
    col = C.COLS
    out = []
    for r in records:
        service = str(r.get(col["service"], "")).strip()
        if service not in C.BRAND_MAP:
            continue
        media = str(r.get(col["media"], "")).strip()
        d = _iso_date(r.get(col["date"]) or r.get(col["date_alt"]))
        if not d:
            continue
        cost = _num(r.get(col["cost"]))
        if not cost:
            cost = _num(r.get(col["cost_alt"]))
        nmedia = C.norm_media(media)
        out.append({
            "service": service,
            "media": nmedia,
            "camptype": C.norm_ct(r.get(col["camptype"]), nmedia),
            "date": d,
            "imp": _num(r.get(col["imp"])),
            "click": _num(r.get(col["click"])),
            "cost": cost,
            "signup": _num(r.get(col["signup"])),
        })
    logs.append(f"[sheet] 표준 행 {len(out)}개 (서비스 {len(set(x['service'] for x in out))}종)")
    return out
