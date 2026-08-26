"""RAW 행을 구글시트에 누적(append)하는 유틸.

기존 리포트 도구(adcon_report / 사방넷 / daou-office)가 매체 API에서 뽑은
표준 행을 여기에 넘겨 시트에 쌓으면, build_data 가 그 시트를 읽어 data.json 을 만든다.

표준 행(dict) 키: service, media, camptype, date, imp, click, cost, signup
필요 환경변수: DAOU_SHEET_ID + GA4_SERVICE_ACCOUNT_JSON(편집자 공유)
"""
import config as C

HEADER = ["서비스", "매체", "캠페인유형", "날짜", "노출수", "클릭수",
          "광고비(마크업포함,VAT별도)", "가입"]
_KEYS = ["service", "media", "camptype", "date", "imp", "click", "cost", "signup"]


def _ws(write=True):
    import gspread
    from google.oauth2.service_account import Credentials
    scope = "https://www.googleapis.com/auth/spreadsheets"
    creds = Credentials.from_service_account_info(C.service_account_info(), scopes=[scope])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(C.SHEET_ID)
    try:
        ws = sh.worksheet(C.SHEET_WORKSHEET)
    except Exception:
        ws = sh.add_worksheet(title=C.SHEET_WORKSHEET, rows=2, cols=len(HEADER))
        ws.append_row(HEADER, value_input_option="USER_ENTERED")
    if not ws.row_values(1):
        ws.append_row(HEADER, value_input_option="USER_ENTERED")
    return ws


def append_raw(rows, logs=None):
    """표준 행 리스트를 RAW 시트에 append. 반환: 추가된 행 수."""
    logs = logs if logs is not None else []
    if not C.sheet_ready():
        logs.append("[write] DAOU_SHEET_ID/서비스계정 없음 → append 스킵")
        return 0
    ws = _ws(write=True)
    values = [[r.get(k, "") for k in _KEYS] for r in rows]
    if values:
        ws.append_rows(values, value_input_option="USER_ENTERED")
    logs.append(f"[write] RAW {len(values)}행 append")
    return len(values)
