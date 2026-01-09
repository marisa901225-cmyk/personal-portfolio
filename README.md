# 📊 My Personal Asset Portfolio

개인 자산/지출/리포트/알림을 통합 관리하는 풀스택 프로젝트입니다.  
백엔드는 홈서버에서 운영하고, 무거운 LLM 추론은 메인PC(GPU)로 분리하여 Tailscale로 연결합니다.

---

## ✅ 핵심 특징

- **자산/거래/환전/배당 관리**: 포트폴리오·거래·현금흐름 통합 관리
- **지출 관리**: 업로드/분류/수정/삭제/복구 + 요약 통계
- **AI 리포트**: DuckDB 기반 분석 + LLM 리포트 생성/저장
- **알림 자동화**: Tasker 웹훅 수집 → 스팸 필터 → 텔레그램 요약
- **뉴스/경기 일정**: RSS/SteamSpy/PandaScore 수집 + RAG 질의응답

---

## 🧭 구성 요약

### 홈서버 (Backend + 알람 LLM)
- FastAPI 백엔드
- 알람/스팸 요약은 로컬 LLM(4b 4q)로 유지

### 메인PC (뉴스/경기 일정용 LLM)
- GPU 기반 llama.cpp 서버 실행
- 뉴스/경기 일정 RAG 응답은 메인PC로 원격 호출

---

## 🛠️ 메인PC 설정 (llama.cpp + Tailscale)

### 1) 모델 준비
- 모델 파일: `gemma-3-12b-it-abliterated-v2.q5_k_m.gguf`

### 2) llama.cpp 서버 실행 (OpenAI 호환)
```bash
/path/to/llama-server \
  -m /path/to/gemma-3-12b-it-abliterated-v2.q5_k_m.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 4096 \
  --n-gpu-layers 999
```

### 3) Tailscale IP 확인
```bash
tailscale status
# 또는
tailscale ip -4
```

### 4) 방화벽
- `8080` 포트 허용 필요

---

## 🔗 홈서버에서 원격 LLM 연결 (뉴스/경기 일정)

### 1) 환경변수 설정 (.env 또는 시스템 환경변수)
```bash
NEWS_LLM_BASE_URL=http://100.65.50.67:8080
NEWS_LLM_MODEL=local
NEWS_LLM_API_KEY=
```

### 2) 동작 방식
- **알람 LLM**: 로컬 모델(`LOCAL_LLM_MODEL_PATH`) 그대로 사용
- **뉴스/경기 일정**: `NEWS_LLM_BASE_URL`로 원격 llama.cpp 호출

---

## ⚙️ 개발/운영 명령어

### Frontend
```bash
npm run dev --prefix frontend
npm run build --prefix frontend
npm run test --prefix frontend
```

### Backend
```bash
python -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

---

## ✅ 주요 환경변수

### 백엔드 일반
- `API_TOKEN`: API 인증 토큰
- `DATABASE_URL`: DB 경로
- `PANDASCORE_API_KEY`: 경기 일정 수집

### 로컬 LLM (알람 처리)
- `LOCAL_LLM_MODEL_PATH`: 로컬 GGUF 경로
- `LOCAL_LLM_THREADS`: 쓰레드 수

### 원격 LLM (뉴스/경기 일정)
- `NEWS_LLM_BASE_URL`: llama.cpp OpenAI 호환 서버 URL
- `NEWS_LLM_MODEL`: 모델명 (기본 `local`)
- `NEWS_LLM_API_KEY`: 필요 시 토큰

---

## 🧪 테스트

```bash
npm run test --prefix frontend
python -m unittest backend/tests
```

---

## 📌 참고

- `devplan/` 폴더에 개선 보고서와 프롬프트가 관리됩니다.
- `dist/` 는 빌드 산출물이므로 직접 수정하지 않습니다.
