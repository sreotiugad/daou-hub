# 브랜드별 RAW 생성 레시피 (학습 정리)

각 브랜드의 기존 리포트 앱을 읽고, raw를 "어떻게 짜는지" 정리한 문서.
daou-hub 수집기(`ingest_*.py`)는 이 규칙을 따른다. 출처 저장소:

| 브랜드 | 저장소 | 핵심 파일 |
|---|---|---|
| 사방넷(+미니·풀필먼트) | `sreotiugad/sabangnet-report` | `app.py` (3260줄) |
| 애드콘(+엔팩스) | `sreotiugad/addcon_report` | `adcon_report.py` (2410줄) |
| 다우오피스(+HR) | `sreotiugad/daou-office-report` | `src/*.py` |

---

## 공통 규칙 (3사 동일) — 이미 수집기에 반영됨

### 광고비 (마크업/VAT)
```
구글 :  총비용(VAT제외)  × 1.1     # VAT 10% 가산
네이버:  salesAmt(VAT포함) ÷ 1.1    # VAT 10% 제거
```
- 별도 '마크업'은 없다(=0). "마크업포함"이라는 컬럼명이지만 실제 계산은 VAT 1.1뿐.
- 근거: adcon_report.py:107-123 `calc_display_cost`, sabangnet app.py:188-199,
  daou-office src/config.py:70 `costMultiplier=1.1`.
- 컬럼 라벨은 브랜드마다 다름(사방넷 "VAT포함" / 애드콘 "VAT별도") — **계산값은 동일**.
- 구현: `ad_config.marked_cost(net, media, markup=0, vat=0.1)`.

### 인증 (네이버 검색광고)
- HMAC-SHA256 서명(X-Timestamp/X-API-KEY/X-Customer/X-Signature). 3사 동일.
- 구현: `ingest_naver_ads._headers` (adcon_report.py:197 와 동일).

### 매체 표기
- 표준은 `네이버` / `구글`. (단, 사방넷미니는 DA 배너 매체가 더 있음 — 아래 특이사항)

---

## 브랜드별 차이 (수집기 보정 포인트)

### 1) 서비스(세부브랜드) 분리
| 브랜드 | 분리 방법 | 근거 |
|---|---|---|
| 사방넷 | **캠페인명 포함어**: `풀필먼트`→풀필먼트, `미니`→사방넷미니, `사방넷`→사방넷 | app.py:174-182 |
| 애드콘 | 계정/서비스 컬럼 기준. 기본 `애드콘`, 엔팩스는 별도 | adcon_report.py:101-105 |
| 다우오피스 | **광고그룹 포함어**: 구분=BSA & adGroup에 `hr` → HR, 그 외 다우오피스 | src/config.py:36-38 |
→ daou-hub 는 `accounts.json` 의 `service` + `service_rules[{contains,service}]` 로 표현.
  (사방넷 예시가 `accounts.example.json` 에 있음)

### 2) 가입(전환) 정의 — **브랜드마다 다름! 가장 주의**
| 브랜드 | 네이버 가입 | 구글 가입 |
|---|---|---|
| 애드콘 | AD_CONVERSION 리포트 **convType=`sign_up` 만** → adgroup 병합 | conversions 중 **category=`SIGNUP`** 만 |
| 사방넷 | AD_CONVERSION **전환일≠노출일 보정** 후 키워드 합산 | (동일 계열) |
| 다우오피스 | (광고 전환 아님) **GA4 키이벤트**(속성별 이벤트명) | GA4 키이벤트 |
- 근거: adcon_report.py:186-192, 1364-1373 / sabangnet app.py:667-747 / daou-office src/config.py:99-106, ga4/client.py:89.
- **구글**: 수집기 반영 완료 — `conversion_action_category=SIGNUP` 만 합산(2쿼리).
- **네이버**: 현재 수집기는 `/stats` 의 `ccnt`(전체 전환) 근사. 정확히는 AD_CONVERSION
  `sign_up` 필터가 필요 → 첫 연동 때 보정(아래 TODO).
- **다우오피스**: 가입은 광고 API가 아니라 **GA4**에서 와야 함 → GA4 수집 필요(아래 TODO).

### 3) 브랜드검색(BS) / DA 배너 — 사방넷 특이
- 사방넷 브랜드검색은 API 비용이 아니라 **계약 고정 일단가**(BS_CONTRACTS, VAT포함, 기간별).
  app.py:109-134. → 수집기에서 BS 캠페인은 계약표로 비용 대체 필요(TODO).
- 사방넷미니는 네이버/구글 외 **DA 배너 매체 다수**(블라인드·리멤버·데이블·디지털캠프·
  네이버페이 등)를 시트에서 읽어 합침. app.py:1322-1429.
  → daou-hub 는 현재 네이버/구글만. DA는 시트/CSV 소스로 별도 적재 가능(폴백 경로 활용).

### 4) 캠페인유형 매핑 (네이버 campaignTp)
```
WEB_SITE→파워링크  SHOPPING→쇼핑검색  BRAND_SEARCH→브랜드검색  POWER_CONTENTS→파워컨텐츠
```
근거 adcon_report.py:512-535 / sabangnet app.py:946. daou-hub `norm_ct`(config.py)로 표준 6종에 매핑.

---

## 권장 아키텍처 — "리포트 앱 재사용 → 창고"

각 브랜드 raw 로직(BS 계약·DA·전환 보정·GA4)은 이미 각 앱에 정확히 구현돼 있다.
daou-hub 에서 **처음부터 재구현하면 숫자가 어긋난다.** 가장 정확한 자동화는:

```
[브랜드 앱들 (사방넷/애드콘/다우오피스)]  ── 매일 9시 헤드리스 실행 ──▶  BigQuery(ads_raw)
        (기존 '리포트 다운로드' 함수 그대로 호출, 결과를 창고에 write)
                                                     │
                                     daou-hub build_data ──▶ data.json ──▶ Vercel
```

- 즉 각 앱에 "raw 생성 → BigQuery 적재" 데일리 잡을 1개씩 붙이는 게 최선(로직 재사용).
- daou-hub 의 `ingest_*.py` 는 그게 어려운 브랜드용 **범용 폴백**(공통 규칙만 정확).

## 매체 수집기 (구현됨)
- 네이버 검색광고: `ingest_naver_ads.py`
- 구글애즈: `ingest_google_ads.py` (가입=SIGNUP 카테고리만)
- **메타**: `ingest_meta.py` (Graph insights, 동영상/디스플레이, complete_registration=가입, spend 그대로)
- **GA4(다우오피스 가입)**: `ingest_ga4.py` (전환 이벤트 → 가입, 광고비 0행). 광고계정엔 `signup_from_ga4:true` 로 중복 방지.

## 첫 연동 때 보정 체크리스트(TODO)
- [x] 다우오피스 가입: GA4 키이벤트 수집 추가 → `ingest_ga4.py` (conversion_event 이름만 확인)
- [x] 메타 수집 추가 → `ingest_meta.py`
- [ ] 네이버 가입: AD_CONVERSION `sign_up` 필터(현재 ccnt 전체전환 근사)
- [ ] 사방넷 브랜드검색: 계약 고정단가표로 비용 대체
- [ ] 사방넷미니 그 외 DA 배너(블라인드·리멤버·데이블 등): 시트/CSV 소스로 별도 적재
- [ ] 수기 엑셀 1일치와 대조해 광고비·가입 숫자 일치 확인
