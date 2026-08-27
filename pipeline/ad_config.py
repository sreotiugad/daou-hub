"""광고계정 설정 로더.

브랜드마다 네이버/구글 광고계정과 '사업 규칙'(마크업·VAT·서비스 분류)이 다르다.
그 설정을 코드가 아니라 데이터로 둔다.

우선순위:
  1) 환경변수 DAOU_AD_ACCOUNTS  (JSON 문자열, 시크릿에 넣기 좋음 — 키 포함)
  2) pipeline/accounts.json      (로컬 파일; .gitignore 로 커밋 제외)
  없으면 빈 설정 → 수집 스킵(사이트는 기존 data.json 유지).

계정 스키마 (accounts.example.json 참고):
{
  "naver":  [ {label, customer_id, api_key, secret_key, service, markup, vat, service_rules?} ],
  "google": [ {label, customer_id, login_customer_id?, service, markup, vat, service_rules?} ],
  "defaults": { "markup": 0.15, "vat": 0.10 }
}

service_rules(선택): 한 계정이 여러 세부브랜드를 태울 때 캠페인명으로 분류.
  [{"contains":"미니","service":"사방넷미니"}, {"contains":"풀필","service":"풀필먼트"}]
"""
import os
import json
import config as C

_DEF_MARKUP = 0.15
_DEF_VAT = 0.10


def load(logs=None):
    logs = logs if logs is not None else []
    raw = os.environ.get("DAOU_AD_ACCOUNTS")
    cfg = None
    if raw:
        try:
            cfg = json.loads(raw)
            logs.append("[accounts] env DAOU_AD_ACCOUNTS 사용")
        except Exception as e:
            logs.append(f"[accounts] env JSON 파싱 실패: {e}")
    if cfg is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                logs.append("[accounts] accounts.json 사용")
            except Exception as e:
                logs.append(f"[accounts] accounts.json 파싱 실패: {e}")
    if not cfg:
        logs.append("[accounts] 설정 없음 → 광고 수집 스킵")
        return {"naver": [], "google": [], "defaults": {}}
    cfg.setdefault("naver", [])
    cfg.setdefault("google", [])
    cfg.setdefault("defaults", {})
    return cfg


def markup_vat(acc, defaults):
    mk = acc.get("markup", defaults.get("markup", _DEF_MARKUP))
    vat = acc.get("vat", defaults.get("vat", _DEF_VAT))
    return float(mk), float(vat)


def resolve_service(acc, campaign_name):
    """계정 기본 service, 단 service_rules 에 캠페인명이 걸리면 그쪽으로."""
    for rule in acc.get("service_rules", []) or []:
        needle = str(rule.get("contains", "")).strip()
        if needle and needle in str(campaign_name or ""):
            return rule.get("service")
    return acc.get("service")


def marked_cost(net_cost, markup, vat):
    """순 매체비(VAT별도) → 광고비(마크업포함, VAT포함)."""
    return round(float(net_cost) * (1.0 + markup) * (1.0 + vat))
