# Daou Hub — 데이터 연결 가이드

정적 프론트(`daou-universe/index.html`)는 광고 API를 직접 부르지 않는다.
무거운 수집은 하루 1번만 돌고 결과(RAW)는 **구글시트**에 누적되며,
파이프라인이 그 시트를 읽어 **`daou-universe/data.json`** 을 만든다.
프론트는 `data.json` 만 읽으므로 1년치도 즉시 렌더된다.

```
매체 API (기존 리포트 도구)  ──append──▶  📊 구글시트 RAW  ──build_data──▶  data.json  ──fetch──▶  🖥️ Daou Hub
   (adcon_report 등, 키 필요)                (누적 원장)         (매일 9시)        (CDN)          (index.html)
```

`data.json` 이 없거나 키가 없으면 프론트/파이프라인 모두 **자동 샘플(데모)** 로 동작한다.
→ 키가 없어도 사이트는 뜨고, 키를 넣으면 실데이터로 바뀐다. (우상단 뱃지: 데모/실데이터)

## 내일 아침 — 이것만 채우면 됨

`pipeline/.env.example` 참고. 로컬은 `.env`, 배포는 GitHub Actions Secrets 에 등록.

| 환경변수 | 용도 | 필수 |
|---|---|---|
| `DAOU_SHEET_ID` | RAW 누적 스프레드시트 ID | ✅ |
| `GA4_SERVICE_ACCOUNT_JSON` | 서비스계정 JSON (시트에 편집자로 공유) | ✅ |
| `DAOU_SHEET_WORKSHEET` | RAW 탭 이름 (기본 `RAW`) | – |
| `NAVER1_CUSTOMER_ID/API_KEY/SECRET_KEY` | 검색광고: 검색량·경쟁·연관·예상CPC | 선택 |
| `NAVER_DEV_CLIENT_ID/SECRET` | DataLab(성별·연령·추이) + 검색 API(콘텐츠수) | 선택 |
| `YOUTUBE_API_KEY` | YouTube 영상 순위·썸네일 | 선택 |
| `DAOU_KEYWORDS` | 분석할 키워드(쉼표) | 선택 |

> 키워드 분석 실데이터 소스 정리: **검색량·경쟁·연관·예상CPC** = 검색광고 키 /
> **성별·연령·추이·콘텐츠수** = 네이버 개발자앱(DataLab·검색) / **영상 순위** = YouTube.
> **시간대별·경쟁 광고순위**는 공개 API가 없어 모델 추정으로 표시된다.

> RAW 를 시트에 **적재**하는 매체 API 키(GADS_*, NAVER2_*, META_* 등)는
> 그 수집을 담당하는 기존 도구(`adcon_report.py` 등)에 넣는다. 이 파이프라인은 시트를 **읽기**만 한다.

## 로컬 실행

```bash
pip install -r pipeline/requirements.txt
cd pipeline && python build_data.py     # → ../daou-universe/data.json
```

## 자동화 (이미 세팅됨)

`.github/workflows/daily-data.yml` 이 **매일 09:00 KST** 에 `build_data.py` 를 돌려
`data.json` 을 갱신·커밋한다. GitHub Secrets 에 위 값만 넣으면 끝.
수동 실행: Actions 탭 → *Daily Daou Hub data* → Run workflow.

## RAW 를 시트에 적재하는 쪽 연결

기존 리포트 도구가 매체에서 뽑은 표준 행을 `sheet_writer.append_raw(rows)` 로 넘기면 된다.
표준 행: `{service, media, camptype, date(YYYY-MM-DD), imp, click, cost, signup}`
(시트 헤더가 이미 `서비스/매체/캠페인유형/날짜/노출수/클릭수/광고비(마크업포함,VAT별도)/가입` 형식이면 그대로 읽힌다.
다르면 `.env` 의 `COL_*` 로 매핑.)

## 파일

| 파일 | 역할 |
|---|---|
| `config.py` | 브랜드 계층·컬럼 매핑·env 로딩 |
| `sheet_source.py` | 시트 RAW → 표준 행 |
| `aggregate.py` | 표준 행 → report(일별 배열·매체·캠페인 비율) |
| `keywords_naver.py` | 네이버 키워드툴 실검색량·경쟁·연관 |
| `sample.py` | 샘플 data.json + 키워드 보조지표 모델러 |
| `build_data.py` | 오케스트레이터 → `data.json` |
| `sheet_writer.py` | 표준 행 → 시트 RAW append (수집 도구용) |

## 배포 (Vercel)

`daou-universe/` 를 정적 배포하면 됨. Vercel Root Directory = `daou-universe`.
`index.html`(Hub)이 진입점, `data.json` 을 같은 경로에서 읽는다.
`landing.html` 은 소개용 마케팅 페이지(선택).
