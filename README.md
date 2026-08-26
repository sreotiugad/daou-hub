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
