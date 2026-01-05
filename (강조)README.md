# 내 포트폴리오

홈서버 + Tailscale로 돌리는 개인 자산관리 앱

---

## 🎯 핵심 기능

- 자산 추가/매수/매도 → 평단가/실현손익 자동 계산
- 한투 API로 국내/해외 시세 자동 연동
- 대시보드: 총자산, 6개월 추이 그래프, 포트폴리오 비중, 리밸런싱 알림
- 거래내역 전체 조회 (검색/필터/페이징)
- API 토큰 잠금, 매일 자동 백업

---

## 🚀 빠른 실행

### 프론트 (로컬)
```bash
npm ci && npm run dev
# → http://localhost:5173
```

### 백엔드 (홈서버)
```bash
# systemd 쓰면
sudo systemctl restart myasset-backend.service

# 수동 실행
source backend/.venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

---

## ⚙️ 환경변수

### 백엔드 `.env`
```bash
API_TOKEN=your_secret_token
DATABASE_URL=sqlite:///backend/portfolio.db  # 선택
KIS_ENABLED=auto  # auto/1/0
BACKUP_ARCHIVE_PASSWORD=your_backup_password  # 설정 시 zip 암호화 압축
```

### KIS 연동
`~/KIS/config/kis_user.yaml` 필요 (템플릿: `open-trading-api/kis템플릿.yaml`)

---

## 📄 리포트 API (읽기 전용)

로컬 AI가 리포트를 만들 때 사용하는 엔드포인트입니다.

- `GET /api/report` (옵션: `year=YYYY`, `month=MM`)
- `GET /api/report/yearly?year=YYYY`
- `GET /api/report/monthly?year=YYYY&month=MM`
- `GET /api/report/quarterly?year=YYYY&quarter=Q`
- `GET /api/report/monthly/summary?year=YYYY`
- `GET /api/report/quarterly/summary?year=YYYY`
- `GET /api/report/ai?year=YYYY&month=MM` (또는 `quarter=Q`, `top_n=1~50`)

인증 토큰을 쓰는 경우 헤더에 `X-API-Token`을 추가하세요.

예시:
```bash
curl -sS -H "X-API-Token: $API_TOKEN" \
  "http://127.0.0.1:8000/api/report/quarterly?year=2025&quarter=1"
```

---

## 🔄 배포

### GitHub 푸시
```bash
cd /path/to/personal-portfolio
git status              # 변경사항 확인
git add -A
git commit -m "커밋 메시지"
git push origin main
```

### 프론트 (Vercel)
```bash
cd /path/to/personal-portfolio
npx vercel --prod
# 또는 git push (GitHub 연동 시 자동 배포)
```

### 백엔드 (홈서버)
```bash
cd /path/to/personal-portfolio
git pull
sudo systemctl restart myasset-backend.service
```

---

## 📦 백업/복원

### 백업
```bash
./backend/backup_db.sh
# → /mnt/one-touch/personal-portfolio-backend-backup/
# BACKUP_ARCHIVE_PASSWORD 설정 시 .db.zip 으로 저장됨
```

### 복원
```bash
sudo systemctl stop myasset-backend.service
cp /mnt/one-touch/.../portfolio_20250101_030000.db backend/portfolio.db
sudo chown -R <user>:<user> backend/portfolio.db*
sudo systemctl start myasset-backend.service
```

---

## ⏰ Cron 작업
```bash
# 📧 스위치기어 견적 메일 (월 9시)
0 9 * * 1 cd /home/dlckdgn/switchgear-estimate-app/backend && /home/dlckdgn/.nvm/versions/node/v22.21.1/bin/node send-db-email.js --no-dropbox >> /home/dlckdgn/switchgear-estimate-app/backend/send-mail-weekly.log 2>&1

# 📦 드롭박스 백업 (월수금 9:05)
5 9 * * 1,3,5 cd /home/dlckdgn/switchgear-estimate-app/backend && /usr/bin/flock -n /tmp/switchgear_dropbox_db.lock -c "/home/dlckdgn/.nvm/versions/node/v22.21.1/bin/node send-db-email.js --no-email --no-excel" >> /home/dlckdgn/switchgear-estimate-app/backend/send-db-dropbox.log 2>&1

# 💰 미국장 시세 동기화 (화~토 6:30)
30 6 * * 2-6 API_TOKEN=RL=http://127.0.0.1:8000 /home/dlckdgn/personal-portfolio/backend/scripts/sync_prices.sh >> /home/dlckdgn/personal-portfolio/backend/sync.log 2>&1

# 💾 포트폴리오 DB 백업 (일 4시)
0 4 * * 0 /home/dlckdgn/personal-portfolio/backend/scripts/backup_db.sh >> /home/dlckdgn/personal-portfolio/backend/backup_db.log 2>&1
```

### Cron 백업/복구
```bash
# 백업
crontab -l > backend/crontab.bak

# 복구
crontab backend/crontab.bak
```

---

## 🔧 자주 터지는 것들

| 문제 | 해결 |
|------|------|
| systemd 경고 | `sudo systemctl daemon-reload` |
| 포트 충돌 | `sudo ss -ltnp \| rg ':8000'` |
| DB 권한 오류 | `sudo chown <user>:<user> backend/portfolio.db*` |
| 401 토큰 에러 | 프론트 설정 토큰 ↔ 서버 `API_TOKEN` 확인 |
| KIS 인증 실패 | `~/KIS/config/kis_user.yaml` 확인 |
| 티커 검색 실패 | `open-trading-api/stocks_info/` 엑셀 파일 확인 |

---

## 📝 최근 수정

### 2026-01-02
- 💳 카드사/통장 거래내역 자동 임포트 스크립트 추가 (`scripts/expenses/import_expenses.py`)
- 🤖 자동 카테고리 분류 (10개 카테고리, 180+ 키워드)
- 🎓 **ML 학습 기능 추가** (`scripts/expenses/learn_merchant_patterns.py`) - 기존 DB를 학습해서 분류 정확도 향상
- 💰 **투자 카테고리 추가** - 증권사/ISA 대형 이체(50만원+)를 일반 이체와 구분
- � **수동 조정 도구** (`scripts/expenses/fix_categories.py`) - 잘못 분류된 항목 쉽게 수정
- 📊 **프론트엔드 가계부 UI 추가** - 월별 지출/수입 분석, 카테고리별 차트
- �🔍 중복 제거 기능 (MD5 해시 기반)
- 📊 기존 DB 데이터 전체 재분류 (기타 305건 → 0건)

### 2025-12-23
- README 대폭 정리 (나 혼자 보기 편하게)

### 2025-12-18
- 거래내역 전체 조회 페이지 추가

### 2025-12-03
- 자산 추이 그래프 버그 수정
- API 토큰 보안 강화

---

## ✅ 검사 명령어 (Health / Typecheck / Test / Build)

프로젝트 상태 점검 및 기본 검증에 사용하는 명령어 모음입니다.

프론트엔드 (의존성 설치, 타입체크, 테스트, 빌드)
```bash
npm ci
npm run typecheck    # TypeScript 타입 검사
npm run test         # Vitest 단위 테스트 실행
npm run build        # 프로덕션 빌드 생성
```

백엔드 (가상환경 생성, 의존성 설치, 서버 상태 확인)
```bash
python -m venv backend/.venv && source backend/.venv/bin/activate
pip install -r backend/requirements.txt
# 개발 서버 실행
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

백엔드 테스트 (unittest)
```bash
backend/.venv/bin/python -m unittest discover -s backend/tests -p "test_*.py"
```

서비스/운영 상태 확인
```bash
sudo systemctl restart myasset-backend.service
sudo systemctl status myasset-backend.service --no-pager

# HTTP 헬스 체크
curl -sS http://127.0.0.1:8000/health | jq .

# 인증이 필요한 엔드포인트 예시
curl -sS -H "X-API-Token: $API_TOKEN" http://127.0.0.1:8000/api/settings
```

간단한 DB 확인 (SQLite 사용 시)
```bash
sqlite3 backend/portfolio.db "SELECT COUNT(*) FROM assets;"
```

---

## 💳 카드/통장 거래내역 자동 임포트

### 🎯 개요
카드사나 은행에서 다운로드한 Excel/CSV 파일을 자동으로 파싱해서 DB에 넣어줍니다.
- ✅ 자동 카테고리 분류 (식비, 교통, 쇼핑, 통신 등)
- ✅ 중복 자동 제거 (같은 거래 재임포트 방지)
- ✅ 다중 파일 일괄 처리

### 📁 지원 형식
- Excel: `.xlsx`, `.xls`
- CSV: `.csv` (UTF-8/CP949 자동 감지)

### 📋 필수 컬럼
파일에 이 컬럼들이 있어야 함 (컬럼명은 자동으로 찾음):

| 필수 | 컬럼명 예시 |
|------|-----------|
| 날짜 | 일자, 거래일, 거래일자, 승인일자 |
| 가맹점 | 가맹점, 가맹점명, 상호, 적요, 내역 |
| 금액 | 금액, 거래금액, 이용금액, 승인금액 |
| 결제수단 (선택) | 카드, 카드명, 계좌, 은행 |

> **💡 팁**: 결제수단 컬럼이 없으면 파일명을 사용

### 🚀 사용법

```bash
# 가상환경 활성화
source backend/.venv/bin/activate

# 단일 파일
python3 scripts/expenses/import_expenses.py 우리카드_2025.xlsx

# 여러 파일 한번에
python3 scripts/expenses/import_expenses.py 신한카드.xlsx 국민은행.csv 토스뱅크.xlsx

# 미리보기만 (저장 안 함)
python3 scripts/expenses/import_expenses.py --dry-run 현대카드.xlsx

# 자동 카테고리 끄기
python3 scripts/expenses/import_expenses.py --no-auto-category 거래내역.xlsx
```

### 🤖 자동 카테고리 분류

**2단계 분류 시스템:**
1. **🎓 학습된 패턴** (1순위): 기존 DB 데이터를 분석해서 학습한 가맹점-카테고리 매핑
2. **🧠 내장 규칙** (2순위): 180+ 키워드 기반 휴리스틱 분류

#### 학습 패턴 업데이트
```bash
# 현재 DB 데이터를 학습해서 분류 규칙 갱신
source backend/.venv/bin/activate
python3 scripts/expenses/learn_merchant_patterns.py

# 생성 파일:
#   - backend/learned_merchant_rules.py (분류 코드)
#   - backend/learned_merchant_rules.json (JSON 데이터)
```

#### 내장 규칙 (Fallback)

| 카테고리 | 인식 키워드 |
|---------|-----------|
| **투자** | 네이버파이낸셜 50만원+, 증권사 10만원+ (ISA, 증권계좌 입금) |
| **식비** | 마트, 홈플러스, GS25, CU, 스타벅스, 배민, 버거킹 등 |
| **교통** | 지하철, 버스, 택시, 주차, 주유, 코레일, KTX 등 |
| **통신** | SKT, KT, LG유플러스, 아파트관리비 등 |
| **구독** | 넷플릭스, 유튜브, 멜론, 구글플레이, 당비 등 |
| **쇼핑** | 쿠팡, 11번가, G마켓, 다이소, 올리브영 등 |
| **이체** | 계좌이체, 송금, 개인 이름 (한글 2-4자), 소액 증권 이체 |
| **급여** | 급여, salary, 월급 |
| **기타수입** | 캐시백, 포인트, 이자 |

### 📊 출력 예시
```
🚀 거래내역 임포트 시작 (2개 파일)

📄 파일 읽는 중: 우리카드_2025.xlsx
✅ 152개 거래 발견
  • 총 152개 | ✅ 추가 145개 | ⏭️ 중복 7개

============================================================
📊 전체 요약
  • 처리한 파일: 2개
  • 총 거래: 304개
  • ✅ 새로 추가: 287개
  • ⏭️ 중복 스킵: 17개
============================================================
```

### 🔍 중복 감지
`(거래일, 가맹점명, 금액, 결제수단)` 조합으로 MD5 해시 생성해서 중복 체크.
같은 파일 여러 번 임포트해도 한 번만 저장됨.

### 💡 팁
1. 파일명 잘 짓기: `우리카드_2025년.xlsx`, `국민은행_2025_01.csv`
2. 컬럼 순서 상관없음 (자동 감지)
3. 금액: 음수 = 지출, 양수 = 수입
4. 임포트 후 확인: `GET /api/expenses/summary`

### 🔧 수동 카테고리 조정
자동 분류가 잘못된 경우 (예: 50만원+ 쇼핑을 투자로 오분류):

**방법 1: 헬퍼 스크립트 사용 (권장)**
```bash
# 의심스러운 항목 자동 검색
python3 scripts/expenses/fix_categories.py --find

# 특정 카테고리만 검사
python3 scripts/expenses/fix_categories.py --find --category 투자

# ID 123번을 쇼핑으로 변경
python3 scripts/expenses/fix_categories.py --update 123 --to 쇼핑
```

**방법 2: API 직접 호출**
```bash
curl -X PATCH http://localhost:8000/api/expenses/{id} \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $API_TOKEN" \
  -d '{"category": "쇼핑"}'
```

**방법 3: 프론트엔드에서 직접 수정**

---

## 브랜치 정보

| 브랜치 | 설명 |
|--------|------|
| `main` | 메인 브랜치 |
| `feature/yearly-cashflow` | 연도별 입출금 관리 기능 (검토 중) |
