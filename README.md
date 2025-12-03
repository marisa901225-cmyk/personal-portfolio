# MyAsset Portfolio

개인용 자산 포트폴리오를 관리하기 위한 웹 애플리케이션입니다.  
프론트엔드는 Vite + React 19 + TypeScript, 백엔드는 FastAPI + SQLite로 구성되어 있으며,  
Tailscale을 이용해 홈 서버에만 private하게 접근하도록 설계했습니다.

## 주요 기능

### 포트폴리오 관리
- **자산 추가/수정/삭제**
  - 자산명, 티커, 카테고리(국내/해외/현금/부동산/기타), 수량, 단가 입력
  - 선택적으로 지수 그룹(S&P500, NASDAQ100, KOSPI200 등)을 지정해 지수별 비중 관리
  - SQLite DB에 영구 저장

- **매수/매도 거래**
  - 자산 목록에서 인라인으로 매수/매도 입력
  - 매수 시 수량 가중 평균으로 평단가 자동 계산
  - 매도 시 실현손익 자동 계산 및 누적 관리
  - 전량 매도 시 해당 종목은 자동으로 포트폴리오에서 제거(소프트 삭제)
  - 모든 거래 내역은 `trades` 테이블에 영구 기록

### 대시보드 & 분석
- **손익 요약**
  - 총 자산, 총 원금, 전체 수익률
  - 실현손익 / 평가손익 분리 표시
  - 카테고리별 비중 차트 (Recharts)

- **지수별 비중 관리**
  - 지수 그룹별 자산 비중 계산
  - 목표 지수 비중 설정 (예: S&P500 60% / NASDAQ100 30% / BOND+ETC 10%)
  - 목표 대비 실제 비중 차이가 5%p 이상일 때 리밸런싱 알림

- **최근 거래 내역**
  - 상단 벨 아이콘을 눌러 최근 20개 거래 기록 확인
  - 각 거래별 실현손익 표시

### 한국투자증권 API 연동
- **티커 자동 검색**
  - 자산명(종목명)을 입력하면 KIS 종목 마스터 기반으로 티커 자동 채우기
  - 국내: 6자리 숫자 코드 (예: `005930`)
  - 해외: `EXCD:SYMB` 형식 (예: `NAS:AAPL`)

- **실시간 가격 동기화**
  - 한국투자증권 Open API로 국내/해외 실거래 시세 조회
  - 모든 가격은 KRW 기준으로 통일
  - 페이지 로드 시 자동 동기화 + 수동 동기화 버튼

## 프로젝트 구조

### 프론트엔드 (`src/`)
- `App.tsx` – 메인 앱 / 뷰 전환 / 상태 관리
- `components/`
  - `Dashboard.tsx` – 대시보드 및 비중/손익 요약 (Recharts 차트)
  - `AssetList.tsx` – 자산 목록, 검색/필터, 매수/매도 인라인 폼
  - `AddAssetForm.tsx` – 자산 추가 폼 (티커 자동 검색 기능 포함)
  - `SettingsPanel.tsx` – 서버 URL 및 목표 지수 비중 설정
- `types.ts` – TypeScript 타입 정의

### 백엔드 (`backend/`)
- `main.py` – FastAPI 애플리케이션 진입점
- `db.py` – SQLite 연결 및 세션 관리
- `models.py` – SQLAlchemy ORM 모델 (`User`, `Asset`, `Trade`, `Setting`)
- `schemas.py` – Pydantic 스키마 (API 요청/응답 모델)
- `auth.py` – API 토큰 인증 로직
- `kis_client.py` – 한국투자증권 API 클라이언트
- `routers/portfolio.py` – 포트폴리오 관련 API 엔드포인트
- `requirements.txt` – 백엔드 의존성
- `portfolio.db` – SQLite 데이터베이스 파일 (Git으로 백업)

## 로컬 실행 방법

### 1. 프론트엔드 (Vite + React)

```bash
cd personal-portfolio

npm install
npm run dev
```

브라우저에서 `http://localhost:5173` (또는 Vite가 안내하는 주소)로 접속합니다.

### 2. 백엔드 (FastAPI + SQLite)

가상환경을 만들고 의존성을 설치합니다.

```bash
cd personal-portfolio

python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
```

`.env` 파일 또는 환경변수로 API 토큰을 설정합니다.

```env
API_TOKEN=원하는_비밀번호
DATABASE_URL=sqlite:///./backend/portfolio.db
```

**개발 서버 실행** (자동 리로드, 포트 8001):

```bash
cd personal-portfolio
source backend/.venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001
```

**운영 서버 실행** (포트 8000):

```bash
cd personal-portfolio
source backend/.venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

- 헬스 체크: `http://서버IP:8000/health`
- API 문서: `http://서버IP:8000/docs` (FastAPI 자동 생성)

**SQLite 데이터베이스**
- 첫 실행 시 `backend/portfolio.db` 파일이 자동 생성됩니다.
- 테이블 구조: `users`, `assets`, `trades`, `settings`
- SQLite 설정: `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`

## API 엔드포인트

### KIS 관련 (기존 유지)
- `GET /health` – 헬스 체크
- `POST /api/kis/prices` – 티커 목록으로 KIS 시세 조회 (KRW 기준)
- `GET /api/search_ticker?q={종목명}` – 종목명으로 티커 검색

### 포트폴리오 관리 (SQLite 기반)
- `GET /api/portfolio` – 전체 포트폴리오 스냅샷 (자산 + 거래 + 요약)
- `POST /api/assets` – 새 자산 추가
- `PATCH /api/assets/{asset_id}` – 자산 정보 수정
- `DELETE /api/assets/{asset_id}` – 자산 삭제 (소프트 삭제)
- `POST /api/assets/{asset_id}/trades` – 매수/매도 거래 처리
- `GET /api/trades/recent?limit=20` – 최근 거래 내역 조회
- `GET /api/settings` – 앱 설정 조회 (목표 지수 비중 등)
- `PUT /api/settings` – 앱 설정 업데이트

## 인증 / 보안 (개인용)

### 백엔드 인증
- 환경변수 `API_TOKEN`이 설정되어 있으면 모든 API 요청 시 헤더 `X-API-Token` 검증
- 토큰이 틀리거나 없으면 HTTP 401 (`invalid api token`) 반환
- `API_TOKEN`이 비어 있으면 인증 강제하지 않음 (개발/테스트 모드)

### 프론트엔드 인증
- 앱 최초 접속 시 전체 화면 로그인 팝업에서 API 비밀번호 입력
- 입력된 토큰은 브라우저 메모리 상태로만 보관 (localStorage 미사용)
- 새로고침 시 재입력 필요

### 네트워크 보안
- **Tailscale 전용 설계**: 홈서버는 Tailscale 네트워크 내에서만 접근 가능
- **UFW 방화벽 설정**:
  ```bash
  sudo ufw allow in on tailscale0 to any port 8000 proto tcp
  ```
  - 일반 인터넷에서는 8000 포트가 보이지 않음
  - Tailscale 100.x.x.x 대역에서만 백엔드 접근 가능

> **주의**: Tailscale을 사용하는 전제이므로, 외부 인터넷에 완전 공개할 계획이라면 추가적인 인증/권한 설계가 필요합니다.

## 배포 전략

### 프론트엔드 (Vercel)
- `npm run build` 결과물을 Vercel 등 정적 호스팅에 배포
- 사용자는 브라우저에서 Vercel 도메인 접속
- Settings 패널에서 `serverUrl`을 Tailscale IP로 설정 (예: `http://100.99.67.34:8000`)

### 백엔드 (홈서버 + systemd)
- **개발 환경**: `uvicorn backend.main:app --reload --port 8001`
- **운영 환경**: systemd 서비스로 등록 (포트 8000)

**systemd 서비스 예시** (`/etc/systemd/system/portfolio-api.service`):
```ini
[Unit]
Description=Personal Portfolio API
After=network.target

[Service]
Type=simple
User=dlckdgn
WorkingDirectory=/home/dlckdgn/personal-portfolio
Environment="API_TOKEN=your_secret_token"
Environment="DATABASE_URL=sqlite:///./backend/portfolio.db"
ExecStart=/home/dlckdgn/personal-portfolio/backend/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

서비스 관리:
```bash
sudo systemctl daemon-reload
sudo systemctl enable portfolio-api
sudo systemctl start portfolio-api
sudo systemctl status portfolio-api
```

### 통신 흐름
1. 사용자가 Vercel 도메인에서 프론트엔드 접속
2. 브라우저(Tailscale 연결 상태)에서 `http://100.99.67.34:8000` API 호출
3. 홈서버 백엔드가 SQLite DB 조회 후 응답

## 백업 전략

### GitHub 자동 백업
- **레포지토리**: 비공개 GitHub 레포
- **백업 대상**: `backend/portfolio.db` (SQLite 데이터베이스)
- **SSH 인증**: 서버에서 SSH 키 생성 및 GitHub 등록 완료

**백업 스크립트 예시** (`tools/backup_db.sh`):
```bash
#!/bin/bash
cd /home/dlckdgn/personal-portfolio
git add backend/portfolio.db
git commit -m "Auto backup: $(date '+%Y-%m-%d %H:%M:%S')"
git push origin main
```

**cron 설정** (매일 새벽 3시 자동 백업):
```bash
0 3 * * * /home/dlckdgn/personal-portfolio/tools/backup_db.sh
```

### 복구 시나리오
1. 새 서버에서 `git clone <private-repo>` 실행
2. 코드 + `backend/portfolio.db` 함께 복구됨
3. venv 재설정 및 uvicorn 실행으로 즉시 서비스 재개

## 사용 방법

1. Tailscale 연결 상태에서 Vercel 도메인 접속
2. 로그인 팝업에서 `API_TOKEN` 입력
3. Settings에서 `serverUrl`을 홈서버 Tailscale IP로 설정 (예: `http://100.99.67.34:8000`)
4. 자산 추가, 매수/매도, 대시보드 확인 등 모든 기능 사용 가능
5. 모든 데이터는 SQLite DB에 영구 저장되며, GitHub에 자동 백업됨
