#!/usr/bin/env bash

# 1. 프로젝트 폴더로 이동
cd /home/dlckdgn/personal-portfolio

# 2. 혹시 깃허브에 누가 코드 올렸을 수 있으니 먼저 땡겨옴 (충돌 방지)
git pull origin main --rebase

# 3. DB 파일만 골라서 스테이징
git add backend/portfolio.db

# 4. 커밋 (변경사항 없으면 조용히 종료)
git commit -m "auto backup: portfolio.db $(date +%F_%T)" || exit 0

# 5. 깃허브로 쏘기
git push origin main
