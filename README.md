# Daou Hub

사방넷 · 애드콘 · 다우오피스 광고 성과와 경쟁 키워드를 한 화면에서 보는 통합 콘솔.

- **사이트**: `index.html` (정적) — `data.json` 을 읽어 렌더. 키가 없으면 데모로 동작.
- **파이프라인**: `pipeline/` — 구글시트 RAW → `data.json`. `pipeline/README.md` 참고.
- **자동화**: `.github/workflows/daily-data.yml` — 매일 09:00 KST 갱신.

## 배포 (Vercel)
저장소를 그대로 Import → Deploy. `index.html` 이 루트라 **Root Directory 설정 불필요.**

## 실데이터 연결
`pipeline/.env.example` 의 값들을 **GitHub → Settings → Secrets → Actions** 에 등록하면
매일 자동으로 `data.json` 이 실데이터로 갱신된다. (필수: `DAOU_SHEET_ID`, `GA4_SERVICE_ACCOUNT_JSON`)

### 경쟁사 DA 소재 실시간 조회 (`api/competitor_ads.py`)
경쟁사 탭의 "운영 중인 DA 광고 소재"는 기본으로 `comp-ads/manifest.json`(GitHub Actions
"FB Ads Capture" 수동 캡처)을 보여주지만, **Vercel 프로젝트 환경변수에 `APIFY_TOKEN`**을
등록하면 Apify(`curious_coder/facebook-ads-library-scraper`)로 임의 경쟁사 키워드를
그때그때(수 초~수십 초) 실시간 조회해 우선 표시하고, 실패 시에만 정적 캡처로 폴백한다.
[apify.com](https://apify.com) → Settings → Integrations 에서 토큰 발급.
비용: 광고 1,000건당 $0.75(Pay-per-event).
