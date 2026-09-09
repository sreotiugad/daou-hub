# Daou Hub

사방넷 · 애드콘 · 다우오피스 광고 성과와 경쟁 키워드를 한 화면에서 보는 통합 콘솔.

- **사이트**: `index.html` (정적) — `data.json` 을 읽어 렌더. 키가 없으면 데모로 동작.
- **파이프라인**: `pipeline/` — 구글시트 RAW → `data.json`. `pipeline/README.md` 참고.
- **자동화**: `.github/workflows/daily-data.yml` — 매일 09:00 KST 갱신.
- **누적 구조**: 기존 사방넷 리포트 앱은 선택 기간을 조회해 엑셀/화면으로 보여주는 방식이고, Daou Hub는 그 결과를 일별 RAW로 저장해 장기 추세와 전후 비교를 만든다.

## 배포 (Vercel)
저장소를 그대로 Import → Deploy. `index.html` 이 루트라 **Root Directory 설정 불필요.**

## 실데이터 연결
`pipeline/.env.example` 의 값들을 **GitHub → Settings → Secrets → Actions** 에 등록하면
매일 자동으로 `data.json` 이 실데이터로 갱신된다. (필수: `DAOU_SHEET_ID`, `GA4_SERVICE_ACCOUNT_JSON`)

## 심사용 AX 포인트

- **실무 적용 기록**: 리포트의 "오늘의 운영 판단"에서 근거, 추천 행동, 담당자, 실행 내용, 상태를 저장하고 CSV로 내보낼 수 있다. 실행 여부를 남겨 실제 업무 적용 증거로 쓸 수 있다.
- **AI 사용량 관리**: Claude 분석 호출 수와 토큰 사용량을 브라우저에 누적 표시해 AI 리소스 효율을 확인할 수 있다.
- **조회형에서 누적형으로 확장**: 사방넷 기존 리포트의 정확한 수집 규칙을 유지하면서, 하루 단위 스냅샷을 RAW 창고에 쌓아 월별·기간별 변화와 운영 판단 이력을 비교한다.
- **광고주 보고서 제작**: 리포트 안에서 누적 RAW CSV와 피벗 CSV를 내려받아 광고주 전달용 엑셀 보고서에 바로 붙일 수 있다.
- **선택 기간 기준 분석**: 리포트 차트와 AI 분석은 선택한 브랜드와 관측 가능한 기간만 사용한다. 90일/1년을 선택해도 실제 관측일이 더 짧으면 관측 기간을 명시한다.
- **출처 구분**: 광고 실데이터, 키워드 실측값, 요일·시간대 모델 추정치를 화면과 AI 컨텍스트에서 분리한다.
- **전환 해석 주의**: GA4 가입은 브랜드 기준 전환으로 사용하며, 매체별 확정 귀속 전환으로 단정하지 않는다.

### 경쟁사 DA 소재 실시간 조회 (`api/competitor_ads.py`)
경쟁사 탭의 "운영 중인 DA 광고 소재"는 기본으로 `comp-ads/manifest.json`(GitHub Actions
"FB Ads Capture" 수동 캡처)을 보여주지만, **Vercel 프로젝트 환경변수에 `APIFY_TOKEN`**을
등록하면 Apify(`curious_coder/facebook-ads-library-scraper`)로 임의 경쟁사 키워드를
그때그때(수 초~수십 초) 실시간 조회해 우선 표시하고, 실패 시에만 정적 캡처로 폴백한다.
[apify.com](https://apify.com) → Settings → Integrations 에서 토큰 발급.
비용: 광고 1,000건당 $0.75(Pay-per-event).
