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
```

### KIS 연동
`~/KIS/config/kis_user.yaml` 필요 (템플릿: `open-trading-api/kis템플릿.yaml`)

---

## 🔄 배포

### 프론트 (Vercel)
```bash
cd /path/to/personal-portfolio
npx vercel --prod
# 또는 git push (GitHub 연동 시)
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

### 2025-12-23
- README 대폭 정리 (나 혼자 보기 편하게)

### 2025-12-18
- 거래내역 전체 조회 페이지 추가

### 2025-12-03
- 자산 추이 그래프 버그 수정
- API 토큰 보안 강화
