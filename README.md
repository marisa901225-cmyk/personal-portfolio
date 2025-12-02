# MyAsset Portfolio

개인용 자산 포트폴리오를 관리하기 위한 작은 웹 앱입니다.  
프론트는 Vite + React + TypeScript, 백엔드는 FastAPI로 구성되어 있으며,  
Tailscale을 이용해 홈 서버에만 private하게 붙도록 설계했습니다.

## 주요 기능

- 자산 추가/삭제
  - 자산명, 티커, 카테고리(국내/해외/현금/부동산/기타), 수량, 단가 입력
  - 선택적으로 지수 그룹(S&P500, NASDAQ100, KOSPI200 등)을 지정해 지수별 비중 관리
- 매수/매도 기록
  - 자산 목록에서 인라인으로 매수/매도 입력
  - 전량 매도 시 해당 종목은 자동으로 포트폴리오에서 제거
  - 실현손익은 누적해서 관리
- 대시보드
  - 총 자산, 실현/평가 손익 요약
  - 카테고리별 비중, 지수별 비중
  - 목표 지수 비중(예: S&P500 6 / NASDAQ100 3 / BOND+ETC 1)과 실제 비중 비교 후 리밸런싱 알림
- 최근 거래 내역
  - 상단 종 아이콘(벨)을 눌러 최근 매수/매도 기록 확인
- 티커 자동 검색
  - Yahoo Finance 검색 API로 종목명 → 티커 자동 채우기
- 가격 동기화
  - 홈서버 백엔드에서 Yahoo Finance 현재가 + USD/KRW 환율을 조회해 KRW 기준 가격으로 동기화

## 프로젝트 구조

- `App.tsx` – 메인 앱 / 뷰 전환 / 상태 관리
- `components/`
  - `Dashboard.tsx` – 대시보드 및 비중/손익 요약
  - `AssetList.tsx` – 자산 목록, 매수/매도, CSV 다운로드
  - `AddAssetForm.tsx` – 자산 추가 폼
  - `SettingsPanel.tsx` – 서버 URL 및 목표 지수 비중 설정
- `backend/`
  - `main.py` – FastAPI 애플리케이션 (시세 조회, 티커 검색)
  - `requirements.txt` – 백엔드 의존성

## 로컬 실행 방법

### 1. 프론트엔드 (Vite + React)

```bash
cd personal-portfolio

npm install
npm run dev
```

브라우저에서 `http://localhost:5173` (또는 Vite가 안내하는 주소)로 접속합니다.

### 2. 백엔드 (FastAPI)

가상환경을 만들고 의존성을 설치합니다.

```bash
cd personal-portfolio/backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`.env` 파일에 API 토큰을 설정합니다.

```env
API_TOKEN=원하는_비밀번호
```

서버 실행:

```bash
cd personal-portfolio/backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --env-file .env
```

- 헬스 체크: `http://서버IP:8000/health`
- 브라우저 확인용 루트 페이지: `http://서버IP:8000/`

## 인증 / 보안 (개인용)

- 백엔드:
  - 환경변수 `API_TOKEN`이 설정되어 있으면,  
    `/api/prices`, `/api/search_ticker` 호출 시 헤더 `X-API-Token`이 동일해야 합니다.
  - 틀리거나 없으면 HTTP 401(`invalid api token`)을 반환합니다.
- 프론트:
  - 앱 처음 접속 시, 전체 화면 로그인 팝업에서 API 비밀번호를 한 번 입력해야 합니다.
  - 이 값은 브라우저 메모리 상태로만 들고 있고, 새로고침하면 다시 입력해야 합니다.

Tailscale을 사용하는 전제를 두고 있으므로,  
실제 외부 인터넷에 완전 공개할 계획이라면 추가적인 인증/권한 설계가 필요합니다.

## 배포 메모

- 프론트: Vercel 등 정적 호스팅에 `npm run build` 결과물을 배포
- 백엔드: 홈서버에서 FastAPI + Uvicorn 실행
  - 예: `http://100.99.67.34:8000` (Tailscale IP)
  - UFW는 `tailscale0` 인터페이스에서만 8000 포트를 허용하는 형태 추천

프론트 Settings에서 `serverUrl`을 Tailscale IP로 맞추고,  
백엔드와 동일한 `API_TOKEN`을 로그인 팝업에서 입력하면, 어디서든(단, Tailscale 접속 상태) 개인 포트폴리오를 조회/관리할 수 있습니다.

