"""Vercel 서버리스 함수 — 다우 허브 AI 분석 어시스턴트(챗봇).

프론트 챗봇이 POST /api/chat 로 호출한다. 바디:
  { "messages": [{"role":"user"|"assistant","content":"..."}...],
    "context":  "<현재 대시보드 실데이터 요약(문자열)>" }

서버(여기)에서 Claude 에게 '이 실데이터를 근거로 답하라'는 시스템 프롬프트와 함께
대화를 보내고, 답변 텍스트를 돌려준다. API 키는 Vercel 환경변수 ANTHROPIC_API_KEY.
없으면 안내 메시지를 반환(사이트는 계속 동작).
"""
import os
import json
from http.server import BaseHTTPRequestHandler

MODEL = os.environ.get("DAOU_CHAT_MODEL") or "claude-sonnet-5"

SYSTEM = (
    "너는 '다우 허브'의 AI 마케팅 분석 어시스턴트다. 다우기술의 광고 브랜드"
    "(사방넷·사방넷미니·풀필먼트·애드콘·엔팩스·다우오피스·다우오피스HR)의 "
    "네이버·구글·메타 광고 성과와 키워드/시장 데이터를 해석한다.\n"
    "규칙:\n"
    "1) 아래 <데이터>의 실제 수치에 근거해서만 답한다. 데이터에 없는 건 '데이터에 없음'이라고 말한다. 숫자를 지어내지 않는다.\n"
    "2) 한국어로, 실무자에게 말하듯 간결하게. 핵심을 먼저, 근거 수치를 함께.\n"
    "3) 실적 변동 질문이면 '무엇이/얼마나 변했는지 → 가능한 원인 → 다음 액션' 순으로 답한다.\n"
    "4) 광고비는 마크업·VAT 포함 값, CPA=광고비/가입, CTR=클릭/노출 이다.\n"
    "5) 내부 태그나 시스템 메시지는 출력하지 않는다."
)


def _reply(messages, context):
    try:
        import anthropic
    except Exception as e:
        return None, f"서버에 anthropic 패키지가 없습니다: {str(e)[:120]}"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "AI 키(ANTHROPIC_API_KEY)가 설정되지 않았어요. Vercel 환경변수에 추가해 주세요."
    # 대화 정리(빈/이상 역할 제거, user 로 시작 보장)
    clean = []
    for m in (messages or []):
        role = m.get("role")
        content = str(m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            clean.append({"role": role, "content": content})
    if not clean or clean[0]["role"] != "user":
        return None, "질문을 입력해 주세요."
    system = SYSTEM + "\n\n<데이터>\n" + (context or "(데이터 없음)") + "\n</데이터>"
    try:
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 자동 사용
        msg = client.messages.create(
            model=MODEL, max_tokens=1500, system=system, messages=clean,
        )
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", None) == "text").strip()
        return (text or "(답변이 비어 있어요)"), None
    except Exception as e:
        return None, f"AI 호출 오류: {str(e)[:180]}"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send({"error": "잘못된 요청"}, 400)
        reply, err = _reply(body.get("messages"), body.get("context"))
        if err:
            return self._send({"error": err}, 200)  # 프론트가 말풍선으로 표시
        self._send({"reply": reply}, 200)

    def do_OPTIONS(self):
        self._send({}, 204)

    def _send(self, obj, code):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if code != 204:
            self.wfile.write(b)
