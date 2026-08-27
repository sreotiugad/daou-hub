# Daou Hub — 데이터 파이프라인 가이드

정적 프론트(`index.html`)는 광고 API를 직접 부르지 않는다. 무거운 수집은
**매일 아침 9시(KST)에 GitHub Actions**가 대신 돌린다. 네가 "리포트 다운로드"를
누르면 API들이 조합해 raw를 만들어 주던 그 과정을, 코드가 자동으로 한다.

```
매일 09:00 KST  (GitHub Actions 크론)
  ① ingest.py    네이버·구글 광고 API 호출 → 표준 raw 행
                 (계정·마크업·서비스분류는 accounts.json / DAOU_AD_ACCOUNTS)
  ② 창고 적재     BigQuery 테이블 ads_raw 에 누적  (BQ 미설정이면 raw/ 폴더)
  ③ build_data   창고 → 집계 → data.json 스냅샷
  ④ commit/push  data.json 커밋 → Vercel 자동 재배포 (서버 연산 0)
```

키/계정이 없으면 파이프라인은 **기존 data.json을 보존**하고, 아무것도 없으면
샘플(데모)로 동작한다. 우상단 뱃지: 데모 / 실데이터.

## 창고 선택 — BigQuery 권장

브랜드가 늘고(사방넷·애드콘·다우오피스·뿌리오…) 광고 raw + 키워드 raw를 함께
누적하므로 **BigQuery**가 맞다. 무료 티어(저장 10GB + 쿼리 1TB/월)로 충분.
BQ를 설정하지 않으면 저장소의 `raw/` 폴더(CSV 누적)로 자동 폴백한다.

읽기 우선순위: **BigQuery → raw/ 폴더 → 구글시트 → 샘플**

## 설정 — 내일 아침 이것만

로컬은 `.env` + `pipeline/accounts.json`, 배포는 GitHub Actions Secrets.

### 1) 광고 계정·사업규칙 (`accounts.json` 또는 Secret `DAOU_AD_ACCOUNTS`)
`pipeline/accounts.example.json`을 복사해 채운다. 계정별로:
- `service` — 이 계정이 태우는 세부브랜드(사방넷/애드콘/…)
- `markup`, `vat` — 광고비(마크업·VAT 포함) 환산율 (기본 0.15 / 0.10)
- `service_rules` — 한 계정이 여러 세부브랜드면 캠페인명으로 분류
- 네이버: `customer_id`, `api_key`, `secret_key`
- 구글: `customer_id` (OAuth 공통키는 아래 env)

### 2) 구글애즈 공통 OAuth (Secrets)
`GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`,
`GOOGLE_ADS_REFRESH_TOKEN`, (MCC면) `GOOGLE_ADS_LOGIN_CUSTOMER_ID`

### 3) BigQuery 창고 (Secrets)
`BQ_DATASET`(예: `daou_hub`), (선택) `BQ_ADS_TABLE`(기본 `ads_raw`), `BQ_PROJECT`,
그리고 `GA4_SERVICE_ACCOUNT_JSON`(서비스계정 JSON). 서비스계정에
**BigQuery Data Editor + BigQuery Job User** 역할을 준다.

### 4) 키워드 실데이터 (선택, Secrets)
`NAVER1_*`(검색량·경쟁·연관·CPC), `NAVER_DEV_*`(성별·연령·추이·콘텐츠수),
`YOUTUBE_API_KEY`(영상 순위·썸네일), `DAOU_KEYWORDS`.

## BigQuery 처음 세팅 (5단계)

1. Google Cloud 콘솔 → 프로젝트 선택/생성 → **결제 사용 설정**(무료 티어라도 카드 필요, 과금 거의 0).
2. **BigQuery API** 사용 설정.
3. BigQuery → 데이터셋 만들기 → 이름 `daou_hub`, 위치 `asia-northeast3(서울)`.
4. IAM → 서비스계정(`daou-hub-reader@…`)에 **BigQuery 데이터 편집자** + **BigQuery 작업 사용자** 역할 부여.
5. GitHub Secret `BQ_DATASET=daou_hub`, `GA4_SERVICE_ACCOUNT_JSON`=서비스계정 JSON 등록.
   → 테이블 `ads_raw`는 파이프라인이 자동 생성한다.

## 로컬 실행

```bash
pip install -r pipeline/requirements.txt
cd pipeline
python ingest.py --sample --backfill 3   # 키 없이 배선 검증(더미 raw 생성)
python ingest.py --backfill 1            # 어제치 실제 수집(계정 설정 시)
python ingest.py --backfill 400          # 최초 1년치 백필
python build_data.py                     # 창고 → ../data.json
```

## 새 브랜드 추가

`config.py`의 `BRAND_MAP` / `GROUP_SUBS` / `GROUPS`에 한 줄 추가하고
(예: 뿌리오), `accounts.json`에 그 브랜드 광고계정을 넣으면 끝.
프론트 탭도 그 그룹을 자동 인식한다(데이터 있는 세부브랜드만 노출).

## 파일

| 파일 | 역할 |
|---|---|
| `ingest.py` | 오케스트레이터: 광고 API → 표준행 → 창고(BQ/raw) |
| `ingest_naver_ads.py` | 네이버 검색광고 수집(캠페인·일자 실적) |
| `ingest_google_ads.py` | 구글애즈 수집(GAQL) |
| `ad_config.py` | 계정·마크업·서비스 규칙 로더 |
| `bq_store.py` | BigQuery 창고(적재·조회) |
| `raw_store.py` | raw/ 폴더 창고(BQ 폴백) |
| `sheet_source.py` | 구글시트 읽기(추가 폴백) + 표준행 변환 |
| `aggregate.py` | 표준행 → report(일별 집계) |
| `build_data.py` | 창고 → 집계 → data.json (실데이터 보존 가드) |
| `keywords_naver.py` | 네이버 키워드툴 → 경쟁 분석 |
| `sample.py` | 키 없을 때 샘플 데이터 |

## 배포 (Vercel)

저장소 루트를 그대로 정적 배포. `index.html`(Hub)이 진입점, 같은 경로의
`data.json`을 읽는다. Root Directory 설정 불필요.
