# 내 포트폴리오 (MyAsset Portfolio)

개인 자산 관리를 위해 직접 만든 웹 서비스입니다.  
집에 있는 서버(홈서버)에 데이터를 안전하게 저장하고, 어디서든(Tailscale 연결 시) 내 자산을 확인할 수 있습니다.

---

## 🚀 주요 기능

### 1. 자산 관리
- **자산 추가**: 주식, ETF, 현금, 부동산 등 내 모든 자산을 등록할 수 있습니다.
- **매수/매도**: 자산을 사고팔 때마다 기록하면, 평균단가와 실현손익을 자동으로 계산해 줍니다.
- **자동 시세 연동**: 한국투자증권 API를 통해 국내/해외 주식의 현재 가격을 실시간으로 불러옵니다. (티커만 입력하면 끝!)

### 2. 거래 내역 (전체 조회)
- **전체 거래기록**: 거래가 많이 쌓여도 과거 기록까지 페이지로 계속 조회할 수 있습니다.
- **검색/필터**: 자산명/티커 검색 + 매수/매도 필터로 빠르게 찾을 수 있습니다.

### 3. 대시보드 (한눈에 보기)
- **총 자산 & 수익률**: 내 돈이 얼마나 불어났는지 바로 확인할 수 있습니다.
- **자산 추이 그래프**: 지난 6개월간 내 자산이 어떻게 변했는지 그래프로 보여줍니다. (매일 밤 자동 기록)
- **포트폴리오 비중**: 어떤 자산에 얼마나 투자했는지 파이 차트로 보여줍니다.
- **리밸런싱 알림**: 내가 정한 목표 비중(예: 미국주식 60%, 채권 40%)에서 많이 벗어나면 알려줍니다.

### 4. 보안 & 백업
- **비밀번호 잠금**: 앱을 켤 때마다 내가 설정한 API 비밀번호를 입력해야만 내용이 보입니다.
- **안전한 접속**: Tailscale이라는 보안 네트워크를 통해서만 접속할 수 있어, 해킹 걱정이 없습니다.
- **자동 백업**: 소중한 자산 데이터는 매일 새벽 자동으로 깃허브(GitHub) 비공개 저장소에 백업됩니다.

---

## 🛠️ 사용 방법

1. **접속하기**: Tailscale이 켜진 기기(폰, 노트북)에서 배포된 주소(Vercel)로 들어갑니다.
2. **로그인**: 설정해둔 API 비밀번호를 입력합니다.
3. **서버 연결**: 처음 한 번만 '설정' 메뉴에서 홈서버 주소(`http://100.x.x.x:8000`)를 입력해 줍니다.
4. **자산 등록**: '자산 추가' 버튼을 눌러 내 종목들을 등록합니다. (이름만 치면 티커는 자동!)
5. **거래 내역 보기**: '거래 내역' 메뉴에서 과거 거래까지 모두 조회합니다. (검색/필터/더 불러오기 지원)

---

## 🔁 배포 / 업데이트 (복붙용 치트시트)

### 1. 프론트엔드(Vercel) 다시 배포

로컬(개인 PC)에서 프로젝트 폴더로 이동한 뒤:

```bash
cd /path/to/personal-portfolio
npx vercel --prod
```

- 이미 Vercel 프로젝트랑 연결해 둔 상태라면 위 두 줄만 실행하면 새 버전이 배포됩니다.
- 처음 연결하는 거라면 한 번은 `npx vercel`만 실행해서 프로젝트 링크를 먼저 만들어야 합니다.

GitHub 연동을 써도 된다면:

```bash
cd /path/to/personal-portfolio
git add .
git commit -m "update frontend"
git push
```

만 해도 Vercel이 자동으로 새 빌드를 올립니다.

### 2. 백엔드 코드 갱신 + 재시작 (systemd)

홈서버에서 (FastAPI 백엔드가 systemd 서비스로 돌아가는 상태라고 가정):

```bash
cd /path/to/personal-portfolio
git pull
sudo systemctl restart myportfolio-backend.service
```

- `myportfolio-backend.service` 부분은 실제 서비스 이름에 맞게 한 번만 바꿔 두면 됩니다.
- 유닛 파일(.service)을 수정한 게 아니라면 `daemon-reload`는 필요 없습니다.

서비스 상태 확인:

```bash
sudo systemctl status myportfolio-backend.service
```

### 3. 포트폴리오 스냅샷(히스토리) 자동 기록 설정

백엔드에는 이미 `POST /api/portfolio/snapshots` 엔드포인트가 있어서 스냅샷을 한 번 찍을 수 있습니다.  
`backend/snapshot_cron.sh` 스크립트를 이용해서 매일 새벽 한 번씩 자동 호출하도록 설정하면,  
대시보드의 6개월 자산 추이 그래프에 데이터가 차곡차곡 쌓입니다.

1) 스크립트 실행 권한 부여 (한 번만):

```bash
cd /path/to/personal-portfolio
chmod +x backend/snapshot_cron.sh
```

2) 크론 등록 (홈서버에서 `crontab -e`):

```cron
0 3 * * * API_TOKEN=여기에_API_TOKEN BACKEND_URL=http://127.0.0.1:8000 /path/to/personal-portfolio/backend/snapshot_cron.sh >/dev/null 2>&1
```

- `API_TOKEN`은 백엔드 환경변수 `API_TOKEN`과 동일한 값으로 넣습니다.
- 백엔드가 다른 포트/주소에서 돌면 `BACKEND_URL`만 바꿔 주면 됩니다.
- 위 한 줄만 설정해 두면, 매일 새벽 3시에 스냅샷이 1건씩 기록됩니다.

## 📝 최근 업데이트 (Change Log)

> 기능을 수정하거나 추가할 때마다 여기에 기록합니다.

### 2025-12-03
- **자산 추이 그래프 수정**: 
  - 처음 시작한 날에도 6개월치 그래프가 뜨는 오류를 고쳤습니다.
  - 데이터가 쌓이기 전에는 "데이터 부족"이라고 뜨게 바꿨습니다.
- **보안 강화**: API 비밀번호를 입력하지 않으면 아예 자산 정보를 볼 수 없게 막았습니다.
- **세션 노트 정리**: 개발 진행 상황을 깔끔하게 요약해서 정리했습니다.

### 2025-12-18
- **거래 내역 메뉴 추가**: 최근 20건만 보이는 문제를 해결하기 위해, 전체 거래기록을 페이지로 계속 조회할 수 있는 화면을 추가했습니다.

---

## ℹ️ 개발 정보 (참고용)

- **프론트엔드**: React (Vercel 배포)
- **백엔드**: Python FastAPI (홈서버 실행)
- **데이터베이스**: SQLite (파일로 저장)
- **네트워크**: Tailscale (사설망)

---

# 3개월 뒤 나를 위한 1페이지 가이드 (설치/실행/운영)

## 설치/실행 방법

### 프론트엔드 (로컬 개발)

```bash
npm ci
npm run dev
```

- 기본 접속: `http://localhost:5173`
- 백엔드 주소(`http://<tailscale-ip>:8000`)와 API 토큰은 **앱의 설정 화면에서 입력**(로컬 저장)

### 백엔드 (로컬/서버 실행)

```bash
python -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt

# (선택) 환경변수 설정 후
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

systemd로 운영 중이면:

```bash
sudo systemctl restart myasset-backend.service
sudo systemctl status myasset-backend.service
```

## 환경변수 (.env) / 설정 파일

### 백엔드 환경변수

- `API_TOKEN` (권장): API 인증 토큰. 요청 헤더 `X-API-Token`과 일치해야 함 (미설정 시 인증 비활성화)
- `DATABASE_URL` (선택): 기본은 `backend/portfolio.db` (SQLite). 예: `sqlite:////absolute/path/portfolio.db`

### 운영 스크립트용 환경변수

- `backend/backup_db.sh`
  - `DB_PATH` (선택): 기본 `backend/portfolio.db`
  - `BACKUP_DIR` (선택): 기본 `/mnt/one-touch/personal-portfolio-backend-backup`
- `backend/snapshot_cron.sh`
  - `API_TOKEN` (필수): 백엔드 `API_TOKEN`과 동일 값
  - `BACKEND_URL` (선택): 기본 `http://127.0.0.1:8000`

### KIS(한국투자증권) 연동 설정

`/api/kis/*` 호출은 `open-trading-api/examples_llm/kis_auth.py` 설정을 사용합니다.

- `~/KIS/config/kis_devlp.yaml` 파일이 필요
- 템플릿: `open-trading-api/kis_devlp.yaml`
- KIS 앱키/시크릿/계좌번호/HTS ID는 이 YAML 파일에만 설정하며, 백엔드 `.env`의 `KIS_*` 환경변수는 현재 코드에서 사용하지 않습니다. (개인 메모용으로만 사용 가능)
- 따라서 필수 백엔드 환경변수 목록에는 KIS 키를 포함하지 않습니다.

## 백업/복원 방법 (SQLite)

### 백업

```bash
./backend/backup_db.sh
```

- 기본 백업 위치: `/mnt/one-touch/personal-portfolio-backend-backup`
- `sqlite3`가 있으면 핫 백업(`.backup`)으로 단일 파일을 생성

### 복원

1) 백엔드 중지

```bash
sudo systemctl stop myasset-backend.service
```

2) 백업 DB를 `backend/portfolio.db`로 덮어쓰기 (DATABASE_URL을 쓰면 해당 경로로)

```bash
cp /mnt/one-touch/personal-portfolio-backend-backup/portfolio_YYYYmmdd_HHMMSS.db backend/portfolio.db
```

3) 권한 정리(서비스 실행 유저 기준)

```bash
sudo chown -R <service-user>:<service-user> backend/portfolio.db*
```

4) 백엔드 재시작

```bash
sudo systemctl start myasset-backend.service
```

## 자주 터지는 문제 / 해결

- `systemctl` 경고(`daemon-reload`): `sudo systemctl daemon-reload` 후 `sudo systemctl restart myasset-backend.service`
- 포트 충돌(8000): `sudo ss -ltnp | rg ':8000'`로 점유 프로세스 확인 후 종료/포트 변경
- DB 권한 오류: 서비스 유저가 `backend/portfolio.db`(및 `-wal`, `-shm`)에 쓰기 권한이 있어야 함 (`chown/chmod` 확인)
- 401 `invalid api token`: 프론트 설정의 토큰 ↔ 서버의 `API_TOKEN`이 불일치(또는 systemd에서 환경변수 로딩 안 됨). `systemctl cat myasset-backend.service`로 `Environment=`/`EnvironmentFile=` 확인
- KIS 인증 실패: `~/KIS/config/kis_devlp.yaml` 누락/값 오류 (템플릿은 `open-trading-api/kis_devlp.yaml`)
- 티커 검색 실패(마스터 파일): `open-trading-api/stocks_info`에 `kospi_code.xlsx`, `kosdaq_code.xlsx`, `overseas_stock_code(all).xlsx` 등이 필요 (없으면 해당 디렉터리의 생성 스크립트 실행)

## Cron (예약 작업) 백업/복원 설정

이 홈서버에는 총 3가지의 중요한 Cron 작업(백업, 시세 동기화, 타 앱용 메일)이 돌고 있습니다.
혹시 모를 설정 삭제 사고에 대비해 백업/복구 방법을 정리해 둡니다.

> **현재 설정 파일 위치**: `backend/crontab.bak` (git으로 관리됨)

### 1) 현재 설정 (복붙용)
```bash
# 1. 스위치기어 견적서 앱 메일 전송 (월요일 09:00)
0 9 * * 1 cd /path/to/switchgear-estimate-app/backend && /usr/bin/node send-db-email.js >> /path/to/switchgear-estimate-app/backend/send-db-email.log 2>&1

# 2. 포트폴리오 로컬 백업 (일요일 04:00)
0 4 * * 0 /usr/bin/env bash /path/to/personal-portfolio/backend/scripts/backup_db.sh >> /path/to/personal-portfolio/backend/backup_db.log 2>&1

# 3. 미국장 마감 후 시세 동기화 + 스냅샷 (화~토 06:30 KST)
30 6 * * 2-6 API_TOKEN=YOUR_SECRET_API_TOKEN BACKEND_URL=http://127.0.0.1:8000 /path/to/personal-portfolio/backend/scripts/sync_prices.sh >> /path/to/personal-portfolio/backend/sync.log 2>&1
```

### 2) 백업하기 (현재 설정을 파일로 저장)
```bash
crontab -l > backend/crontab.bak
```

### 3) 복구하기 (파일을 시스템에 적용)
```bash
crontab backend/crontab.bak
```
- 주의: 기존 설정을 모두 덮어쓰므로 신중하게 실행하세요.

