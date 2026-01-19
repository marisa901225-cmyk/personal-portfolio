# 🛠️ 프로젝트 개선 탐구 보고서 (Project Improvement Exploration Report)

이 보고서는 프로젝트 코드와 설정을 분석하여, **현재 시점에서 아직 적용되지 않은 개선 사항(Pending Items)**만 정리합니다.
이미 적용된 항목의 히스토리/완료 목록은 포함하지 않습니다(적용 완료 개수는 세션 로그에만 기록).

---

## 1. 전체 개선 현황 요약 (Improvement Summary)

<!-- AUTO-SUMMARY-START -->
### 📊 미해결 항목 분포(Distribution, Pending Only)

이번 탐구는 다음 관점에서 “미적용 항목만” 재검증했습니다:
- KIS 연동 모듈의 사이드 이펙트(FS/Logging) 및 비동기 처리 미비점
- 뉴스/e스포츠 수집기의 코드 부채(TODO) 및 하드코딩
- 운영 스크립트 및 테스트 코드의 타입 안전성 및 표준화 여부

총 **7개**의 미해결 개선 항목(Pending)이 식별되었습니다.

#### (1) 우선순위 분포 (Priority, pending only)
| 우선순위 | 개수 |
|:---:|---:|
| P1 | 1 |
| P2 | 2 |
| P3 | 3 |
| OPT | 1 |

#### (2) 카테고리 분포 (Category, pending only)
| 카테고리 | 개수 | 대표 ID 예시 |
|---|---:|---|
| 🧱 운영 안정성 | 2 | `fix-kis-side-effects-001` |
| 🧹 코드 품질 | 3 | `refactor-news-core-001` |
| ⚙️ 성능 최적화 | 1 | `feat-kis-async-update-001` |
| ⚡ 프론트엔드 | 1 | `feat-frontend-optimization-001` |

#### (3) Origin 분포
| Origin | 개수 |
|---|---:|
| manual-idea | 4 |
| static-analysis | 3 |
| test-failure | 0 |
| build-error | 0 |

#### (4) Risk Level 분포
| Risk level | 개수 |
|---|---:|
| critical | 0 |
| high | 2 |
| medium | 3 |
| low | 2 |

#### (5) 우선순위별 한줄 요약
- **P1:** 시스템 전반에 영향을 주는 KIS 연동 모듈의 사이드 이펙트를 최우선 제거
- **P2:** 핵심 자산용 토큰 갱신의 비동기화 및 뉴스 수집기 내부 코드 부채 해소
- **P3:** 운영 스크립트 표준화 및 프론트엔드 번들/뉴스 중복 제거 효율화
<!-- AUTO-SUMMARY-END -->

---

## 2. 🔧 기능 개선 항목 (기존 기능 개선)

<!-- AUTO-IMPROVEMENT-LIST-START -->
### 🔴 치명 (P1)

#### [P1-1] KIS 연동 모듈 Side-Effect 제거 및 경로 안정화
| 항목 | 내용 |
|------|------|
| **ID** | `fix-kis-side-effects-001` |
| **카테고리** | � 운영 안정성 |
| **복잡도** | High |
| **대상 파일** | `backend/integrations/kis/open_trading/kis_auth_state.py`, `backend/integrations/kis/open_trading/domestic_stock/inquire_price/inquire_price.py` 등 generated 모듈 |
| **Evidence** | `kis_auth_state.py`의 홈 디렉터리 생성 로직, generated 모듈의 `sys.path.extend` 및 `logging.basicConfig` 호출 |
| **Origin** | manual-idea |
| **리스크 레벨** | critical |
| **관련 평가 카테고리** | reliability, productionReadiness |

**현재 상태:** `open_trading` 벤더 라이브러리가 import 시점에 홈 디렉터리에 설정 폴더를 생성하고, 전역 로깅(`logging.basicConfig`)을 강제 재설정하며, `sys.path`를 조작합니다.
**문제점 (Problem):** 이는 백엔드 전체의 로깅 설정을 덮어쓰거나, 파일시스템 쓰기 권한이 없는 컨테이너/배포 환경에서 앱 구동을 실패하게 만들 수 있습니다.
**영향 (Impact):** 운영 환경(Docker/CI) 배포 실패 위험 및 로그 유실 가능성.
**원인 (Cause):** 벤더 제공 라이브러리(codegen)가 독립 실행 스크립트 형태로 작성되어 라이브러리 형태의 연동을 고려하지 않음.
**개선 내용 (Proposed Solution):** import 시점의 부작용 코드(경로 생성, 로깅 설정, sys.path 수정)를 모두 제거하고, 필요한 설정은 `backend/integrations/kis/kis_client.py` 등 상위 호출자에서 주입받거나 지연 초기화하도록 수정합니다.
**기대 효과:** 백엔드 구동 안정성 확보 및 로깅 일관성 유지.

- [ ] `kis_auth_state.py`: 경로 생성 로직 제거/지연
- [ ] generated 모듈: `sys.path` 및 `logging` 관련 코드 제거
- [ ] `backend/tests`: 사이드 이펙트 없이 임포트 되는지 검증

### 🟡 중요 (P2)

#### [P2-1] KIS 토큰 갱신 로직 비동기 최적화
| 항목 | 내용 |
|------|------|
| **ID** | `feat-kis-async-update-001` |
| **카테고리** | ⚙️ 성능 최적화 |
| **복잡도** | Medium |
| **대상 파일** | `backend/integrations/kis/token_store.py` |
| **Evidence** | `token_store.py:128`의 `TODO` 주석 ("여기서 비동기 갱신 트리거 가능") |
| **Origin** | static-analysis |
| **리스크 레벨** | high |
| **관련 평가 카테고리** | performance, reliability |

**현재 상태:** 토큰 만료가 임박하거나 만료된 경우, 요청 시점에서 동기(blocking)적으로 갱신을 수행합니다.
**문제점 (Problem):** 다수의 동시 요청이 들어올 경우, 토큰 갱신이 완료될 때까지 모든 요청이 블로킹되거나(락 경합), 불필요한 대기가 발생합니다.
**영향 (Impact):** API 응답 지연 및 스레드 풀 소진 가능성.
**원인 (Cause):** 초기 구현 시 단순성을 위해 동기 갱신 우선 적용.
**개선 내용 (Proposed Solution):** 토큰 만료 1~5분 전 조회 시, 백그라운드 태스크(asyncio Task)로 갱신을 트리거하고 현재 유효한 토큰을 즉시 반환하여 "Lock-Free"에 가까운 조회를 구현합니다.
**기대 효과:** API 평균 응답 속도 개선 및 동시성 처리량 증대.

- [ ] `token_store.py`: `_trigger_async_refresh` 메서드 구현
- [ ] 락 경합 최소화 로직 적용

#### [P2-2] 뉴스/e스포츠 모듈 리팩토링 및 확장성 확보 (PUBG Ready)
| 항목 | 내용 |
|------|------|
| **ID** | `refactor-news-core-001` |
| **카테고리** | 🧹 코드 품질 |
| **복잡도** | Medium |
| **대상 파일** | `backend/services/news/core.py`, `backend/services/news/esports.py` |
| **Evidence** | `esports.py` 내 LoL/Valorant 전용 하드코딩 로직 산재, `core.py` 내 TODO 잔존 |
| **Origin** | manual-idea |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | maintainability, codeQuality |

**현재 상태:** 뉴스 수집 및 e스포츠 데이터 정제 로직이 LoL과 Valorant에 강하게 결합(Hard-coded)되어 있으며, 새로운 종목(예: PUBG)을 추가하려면 코드 전반을 수정해야 합니다.
**문제점 (Problem):** 신규 종목 추가 시 중복 코드가 발생하고, 필터링 규칙(Keywords)이 여러 파일에 하드코딩되어 관리가 어렵습니다.
**영향 (Impact):** 유지보수 비용 증가 및 뉴스 소스/종목 확장 시 버그 발생 위험.
**개선 내용 (Proposed Solution):** e스포츠 종목별 설정(Game Registry)을 도입하여 전용 로직을 추상화하고, 하드코딩된 키워드를 외부 설정이나 상수로 분리합니다. 또한 `core.py`의 `TODO`를 정리합니다.
**기대 효과:** 신규 종목 추가 용이성 확보(PUBG 즉시 추가 가능 구조) 및 코드 가독성 향상.

- [ ] `esports_config.py` (또는 유사) 도입: 종목별 필터/태그 규칙 정의
- [ ] `esports.py`: 하드코딩 로직을 Registry 기반 루프로 교체
- [ ] `core.py`: TODO 항목 구현 및 키워드 상수화
<!-- AUTO-IMPROVEMENT-LIST-END -->

---

## 3. ✨ 기능 추가 항목 (새 기능)

<!-- AUTO-FEATURE-LIST-START -->
### 🟢 보통 (P3)

#### [P3-1] 운영 스크립트 실행 규약 표준화 (CLI/README)
| 항목 | 내용 |
|------|------|
| **ID** | `opt-script-standardization-001` |
| **카테고리** | 🧱 운영 안정성 |
| **복잡도** | Low |
| **대상 파일** | `backend/scripts/common.py`, `backend/scripts/manage.py`, `backend/scripts/README.md` |

**현재 상태:** 운영 스크립트가 산재해 있고, 실행 방법이나 주의사항(DRY-RUN, 백업 필수 여부)이 명시적으로 관리되지 않아 운영 실수 위험이 있습니다.
**개선 내용:** `backend/scripts/README.md`에 스크립트 카탈로그를 정리하고, `common.py`에 공통 로깅/확인 프롬프트 유틸을 추가하여 모든 스크립트가 표준화된 실행 흐름을 따르도록 합니다.
**기대 효과:** 운영 실수 방지 및 스크립트 유지보수 효율성 증대.

#### [P3-2] 프론트엔드 최적화 및 번들링 효율화
| 항목 | 내용 |
|------|------|
| **ID** | `feat-frontend-optimization-001` |
| **카테고리** | ⚡ 프론트엔드 |
| **복잡도** | Medium |
| **대상 파일** | `frontend/vite.config.ts`, `frontend/src/App.tsx` |

**현재 상태:** 일부 라우트나 무거운 라이브러리가 초기 로딩 시 포함되어 번들 크기가 최적화되지 않았습니다.
**개선 내용:** React.lazy를 적극적으로 적용하고, `vite.config.ts`의 `manualChunks` 설정을 정교화하여 초기 로딩 속도를 개선합니다.
**기대 효과:** 초기 로딩 속도 향상(LCP 개선) 및 UX 강화.

#### [P3-3] 뉴스 중복 제거 로직 고도화
| 항목 | 내용 |
|------|------|
| **ID** | `feat-news-deduplication-001` |
| **카테고리** | ⚙️ 성능 최적화 |
| **복잡도** | Medium |
| **대상 파일** | `backend/services/duckdb_refine.py`, `backend/services/news/core.py` |

**현재 상태:** 단순 URL/제목 매칭에 의존하거나 로직이 분산되어 있어 유사 기사가 중복 수집되는 경우가 있습니다.
**개선 내용:** SimHash 또는 임베딩(Vector) 기반의 내용 유사도 비교 로직을 도입하여 중복 제거율을 높이고, 정제 단계를 단일화합니다.
**기대 효과:** 뉴스 브리핑 품질 향상 및 저장소 효율성 증대.
<!-- AUTO-FEATURE-LIST-END -->

---

## 4. 🚀 코드 품질 및 성능 최적화 (OPT)

<!-- AUTO-OPTIMIZATION-START -->
### 🚀 코드 최적화 (OPT-1)

#### [OPT-1] 타입 안전성 강화 및 Type Guard 적용
| 항목 | 내용 |
|------|------|
| **ID** | `opt-type-safety-001` |
| **카테고리** | 🧹 코드 품질 |
| **영향 범위** | 품질 |
| **대상 파일** | `backend/routers/handlers/query_handler.py`, `backend/misc/*` |

**현재 상태:** 일부 유틸리티 및 라우터 핸들러에서 `Any` 타입이 사용되거나 타입 힌트가 누락되어 있습니다.
**최적화 내용:** 주요 데이터 흐름에 Pydantic 모델을 엄격하게 적용하고, `Any` 사용을 제거하여 타입 안정성을 확보합니다.
**예상 효과:** 런타임 타입 에러 방지 및 IDE 자동완성 지원 강화.
**측정 지표:** `mypy` 검사 시 에러/경고 수 감소.
<!-- AUTO-OPTIMIZATION-END -->

---

## 5. 세션 로그 (Session Log)

<!-- AUTO-SESSION-LOG-START -->
### 2026-01-19 (추가: 백엔드/KIS 점검)
- 분석 범위: `backend/integrations/kis/*`(토큰 저장/서킷브레이커/설정 로딩/벤더 코드), `backend/scripts/*`(운영 스크립트 체계/리스크)
- 새로 발견된 미적용 항목 수: 3 (P1 1 / P2 1 / P3 1)
- 적용 완료된 항목 수(이번 세션 기준): 0

### 2026-01-19 (추가)
- 분석 범위: 프론트 데이터 fetching 전략/번들 크기/스트리밍 취소(Abort) 관점 재점검
- 새로 발견된 미적용 항목 수: 3 (P1 1 / P2 1 / P3 1)
- 적용 완료된 항목 수(이번 세션 기준): 0

### 2026-01-19
- 분석 범위: 민감 파일(토큰/DB/백업 데이터) Git 추적 여부 + CI 시크릿 가드 정책/예외 정합성 점검
- 새로 발견된 미적용 항목 수: 0
- 적용 완료된 항목 수(이번 세션 기준): 1 (토큰/백업 데이터 Git 추적 해제 및 가드 정합성 반영)
<!-- AUTO-SESSION-LOG-END -->
