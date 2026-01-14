# 🏗️ 프로젝트 고도화 및 약점 보완 설계안 (Architecture Design)

> 작성일: 2026-01-13
> 목표: 평가 보고서에서 식별된 4대 핵심 약점(UX, 피드백, 관찰 가능성, AI 품질)을 해결하기 위한 구체적인 구현 설계.

---

## 1. 실시간 피드백 시스템 (SSE Backbone)
> **Goal**: 대량 데이터 처리(복원, 업데이트) 및 시스템 상태를 사용자가 실시간으로 인지할 수 있도록 "Push" 메커니즘 구축.

### 1.1 아키텍처 (Backend)
- **SSEManager (Singleton)**:
    - FastAPI 애플리케이션 내에서 전역적으로 이벤트 스트림을 관리.
    - `async generator`를 사용하여 연결된 클라이언트들에게 브로드캐스팅.
    - **Channels**: `system`(전역 알림), `process:{id}`(특정 작업), `portfolio`(데이터 갱신).

- **API Endpoint**:
    - `GET /api/events` (EventSource 연결점)
    - `Keep-Alive` 핑(ping) 로직 포함 (연결 끊김 방지).

- **Implementation Sketch**:
    ```python
    # backend/core/sse.py
    class SSEManager:
        def __init__(self):
            self.active_connections = []
        
        async def publish(self, event: str, data: dict):
            payload = json.dumps({"event": event, "data": data})
            # Broadcast to all queues
    ```

### 1.2 프론트엔드 연동
- **useEventStream Hook**:
    - `EventSource` 객체 관리 (연결/재연결).
    - 수신된 이벤트를 `Zustand` 스토어(`useSystemState`)에 주입.
    - **UX**: 우측 하단 Toast 알림 또는 상단 진행률 프로그레스 바(Progress Bar) 표시.

---

## 2. 관찰 가능성: 스케줄러 & 작업 모니터링
> **Goal**: "백그라운드에서 뉴스와 주가가 수집되고 있는가?"에 대한 불확실성 제거.

### 2.1 데이터베이스 스키마 (`job_execution`)
| 필드명 | 타입 | 설명 |
|---|---|---|
| `id` | Integer (PK) | 작업 고유 ID |
| `job_name` | String | 작업명 (예: `collect_news`, `sync_prices`) |
| `status` | String | `PENDING`, `RUNNING`, `SUCCESS`, `FAILURE` |
| `start_time` | DateTime | 시작 시간 |
| `end_time` | DateTime | 종료 시간 |
| `result_summary` | JSON | 수집된 건수, 처리 결과 요약 |
| `error_message` | Text | 실패 시 에러 트레이스백 |

### 2.2 데코레이터 패턴 (`@track_job`)
- 모든 스케줄러 함수에 데코레이터 적용.
- **동작 방식**:
    1. DB에 `PENDING` 상태로 레코드 생성.
    2. `SSEManager`를 통해 "작업 시작" 이벤트 전송 (UI 스피너 활성화).
    3. 작업 수행 (`try-except`).
    4. 성공/실패 여부 DB 업데이트 및 SSE "작업 완료" 알림 전송.

---

## 3. UX 지능화: 뉴스 위젯 & 대시보드
> **Goal**: 중요한 정보를 사용자가 찾아다니지 않게 함 (Zero-Click Discovery).

### 3.1 뉴스 피드 위젯 (`NewsTickerWidget`)
- **위치**: 대시보드 그리드 최상단 또는 우측 사이드 패널.
- **데이터 흐름**:
    - 기존 `useNewsQuery` 활용 (캐싱된 데이터).
    - 최신 3~5건의 뉴스(경제/게임)를 롤링 또는 리스트 형태로 노출.
- **인터랙션**: 클릭 시 기존 `NewsOverlay`가 해당 뉴스 ID를 포커스하여 열림.

### 3.2 상태 대시보드 (Settings Panel 확장)
- 설정 메뉴 내 "시스템 상태" 탭 추가.
- `job_execution` 테이블 데이터를 조회하여 최근 스케줄러 실행 이력(성공/실패) 표시.
- "지금 실행" 버튼 추가 (수동 트리거).

---

## 4. AI 품질: RAG 사고(Thought) 로깅
> **Goal**: LLM이 왜 그런 답변을 했는지 디버깅하고, 컨텍스트 누락 방지.

### 4.1 로깅 파이프라인
- **로그 파일**: `logs/rag_context.log` (일별 로테이션).
- **기록 내용**:
    - 사용자 쿼리 ("요즘 스팀 게임 추천해줘")
    - **Refined Context**: DuckDB에서 실제 추출된 데이터 덤프.
    - **Final Prompt**: LLM에 최종 전달된 프롬프트 전체.
    - **Response**: LLM 응답.

### 4.2 프롬프트 엔지니어링 개선 (게임/경제)
- **Time-Awareness**: "오늘은 2026년 1월 13일입니다." 명시적 주입.
- **Context-Bound**: "반드시 위 제공된 데이터('Context')에 있는 내용만 기반으로 답변하세요." 제약 강화.
- **Fallback**: 데이터가 없으면 "관련된 최근 데이터를 찾을 수 없습니다."라고 솔직히 답변하도록 유도.

---

## 5. 구현 우선순위 (내일 할 일)
1. **기반 공사**: `SSEManager` 및 `job_execution` 테이블 생성.
2. **연결**: 스케줄러(`scheduler.py`)에 `@track_job` 적용 및 SSE 연동.
3. **가시화**: 프론트엔드 `SSE Hook` 구현 및 대시보드 뉴스 위젯 배치.
4. **지능화**: 텔레그램 봇 RAG 로깅 추가.
