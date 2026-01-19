# 🛠️ 프로젝트 개선 탐구 보고서 (Project Improvement Exploration Report)

이 보고서는 프로젝트 코드와 설정에서 발견된 **미해결 개선 사항(Pending Items)**을 정리하고, 구체적인 해결 방안을 제시합니다.
이미 완료된 항목이나 과거 기록은 포함하지 않으며, 현재 시점의 개선 필요 사항에 집중합니다.

---

## 1. 전체 개선 현황 요약 (Improvement Summary)

<!-- AUTO-SUMMARY-START -->
### 📊 미해결 항목 분포 (Pending Distribution)

현재 코드 정밀 분석 결과, 총 **8개**의 주요 개선 항목이 식별되었습니다.

#### (1) 우선순위 분포 (Priority)
| 우선순위 | 개수 | 의미 |
|:---:|---:|:---|
| **P1** | **1** | 기존 테스트 환경 안정화 및 핵심 로직 보강 |
| **P2** | **4** | 코드 품질 및 유지보수에 중요한 기술 부채 |
| **P3** | **2** | 신규 기능 제안 |
| **OPT** | **1** | 성능 및 구조 최적화 |

#### (2) 카테고리 분포 (Category)
| 카테고리 | 개수 | 대표 ID 예시 |
|---|---:|---|
| 🧪 테스트 | 1 | `test-coverage-001` |
| 🧹 코드 품질 | 2 | `code-quality-ts-001` |
| 🏗️ 아키텍처 | 1 | `arch-scripts-001` |
| 🚀 최적화 | 1 | `opt-dashboard-Data-001` |
| ✨ 기능 | 2 | `feat-logger-001` |
| 🔒 보안 | 1 | `sec-env-001` |

#### (3) 발굴 원인 분포 (Origin)
| Origin | 개수 |
|---|---:|
| test-failure | 0 |
| build-error | 0 |
| static-analysis | 3 |
| manual-idea | 5 |

#### (4) 리스크 레벨 분포 (Risk Level)
| Risk level | 개수 |
|---|---:|
| critical | 0 |
| high | 1 |
| medium | 4 |
| low | 3 |

### 📋 분석 요약
- **P1 (High Priority):** **기존 30여 개의 테스트 코드 안정화** 및 실행 환경 구축이 최우선 과제입니다. (`test-stabilization-001`)
- **P2 (Quality Focus):** 프론트엔드 `any` 타입 제거 및 스케줄러 재시도 로직 등 품질 강화가 필요합니다.
- **P3 & OPT:** 로깅 및 다국어 지원, 대시보드 로딩 최적화를 제안합니다.
<!-- AUTO-SUMMARY-END -->

---

## 2. 기능 개선 및 버그 수정 (P1, P2)

<!-- AUTO-IMPROVEMENT-LIST-START -->
### 🔴 중요 (P1) - 즉시 개선 필요

#### [P1-1] 백엔드 테스트 환경 안정화 및 핵심 로직 보강
| 항목 | 내용 |
|------|------|
| **ID** | `test-stabilization-001` |
| **카테고리** | 🧪 테스트 |
| **복잡도** | Medium |
| **대상 파일** | `backend/tests/`, `backend/services/asset/valuation.py` |
| **Evidence** | `backend/tests/` 내 30개 파일 존재하나 실행 시 20개 이상의 모듈/Import 에러 발생 |
| **Origin** | test-failure |
| **리스크 레벨** | **High** |
| **관련 평가** | testCoverage, productionReadiness |

- **현재 상태:** ✅ **해결됨** (모든 백엔드 테스트 51건 통과 및 환경 안정화 완료)
- **문제점 (Problem):** 테스트가 존재함에도 실행이 불가능하여 실제 코드 변경 시 안정성을 보장하기 어렵던 문제 해결.
- **영향 (Impact):** 이제 테스트를 통해 코드 변경 시 안정성을 보장할 수 있습니다.
- **원인 (Cause):** 라이브러리 버전 차이 혹은 지속적인 테스트 환경 관리 부재 문제를 수정.
- **개선 내용 (Proposed Solution):**
  1.  **`AGENTS.md`** 가이드를 준수하여 테스트 환경 구축 완료.
  2.  실패하던 모든 테스트(AssertionError, Singleton State Leak 등) 수정 완료.
  3.  실현손익 및 자산 평가(`AssetValuation`) 로직 검증 완료.
- **기대 효과:** 자동화 테스트 환경 안정화 및 CI Readiness 확보.

**Definition of Done:**
- [x] `AGENTS.md`에 정의된 `python -m unittest discover backend/tests` 명령 실행 시 전건 통과 (51/51 Pass)
- [x] 자산 평가 서비스 테스트 케이스 검증 완료 (`verify_realized_profit_fix.py`)

---

### 🟡 중요 (P2) - 품질 및 유지보수

#### [P2-1] 프론트엔드 타입 안정성 강화 (Any 제거)
| 항목 | 내용 |
|------|------|
| **ID** | `code-quality-ts-001` |
| **카테고리** | 🧹 코드 품질 |
| **복잡도** | Medium |
| **대상 파일** | `frontend/hooks/usePortfolio.ts`, `frontend/src/shared/api/client/mappers.ts` |
| **Evidence** | `payload: any`, `updates: any` 등 무분별한 `any` 사용 관찰됨 |
| **Origin** | static-analysis |
| **리스크 레벨** | **Medium** |
| **관련 평가** | codeQuality |

- **현재 상태:** API 응답 및 요청 객체에 `any` 타입을 사용하여 TypeScript의 장점을 살리지 못하고 있습니다.
- **개선 내용:** `interface` 또는 DTO를 정의하여 명시적인 타입을 적용하고 `any`를 제거합니다.

**Definition of Done:**
- [ ] `usePortfolio.ts` 내 `any` 타입을 `PortfolioUpdateDTO` 등으로 교체
- [ ] `mappers.ts`의 `safeNum` 함수 등에서 타입 가드 적용

#### [P2-2] 유틸리티 스크립트 경로 하드코딩 제거
| 항목 | 내용 |
|------|------|
| **ID** | `arch-scripts-001` |
| **카테고리** | 🏗️ 아키텍처 |
| **복잡도** | Low |
| **대상 파일** | `backend/scripts/*.py` |
| **Evidence** | 스크립트 내 절대 경로 또는 상대 경로 참조가 환경에 따라 깨질 수 있음 |
| **Origin** | static-analysis |
| **리스크 레벨** | **Low** |
| **관련 평가** | codeQuality, portability |

- **현재 상태:** 여러 파이썬 스크립트들이 프로젝트 루트 경로를 가정하거나 하드코딩된 경로를 사용합니다.
- **개선 내용:** `pathlib`을 사용하여 경로를 동적으로 탐색하거나, 공통 설정 파일(`config.py`)을 참조하도록 수정합니다.

**Definition of Done:**
- [ ] 주요 스크립트 3개 이상에서 하드코딩된 경로를 `Path(__file__).parent` 기반으로 수정

#### [P2-3] 스케줄러 에러 핸들링 및 재시도 로직 추가
| 항목 | 내용 |
|------|------|
| **ID** | `error-handling-scheduler-001` |
| **카테고리** | ⚙️ 안정성 |
| **복잡도** | Medium |
| **대상 파일** | `backend/scheduler.py` |
| **Evidence** | 외부 API 장애 시 스케줄러 잡이 실패하고 로그만 남김 (재시도 부재) |
| **Origin** | manual-idea |
| **리스크 레벨** | **Medium** |
| **관련 평가** | productionReadiness |

- **현재 상태:** KIS나 PandaScore API 일시 장애 시 데이터 수집이 누락됨.
- **개선 내용:** `tenacity` 라이브러 등을 도입하여 일시적 오류 시 지수 백오프(Exponential Backoff) 재시도를 적용합니다.

**Definition of Done:**
- [ ] `services/news/collector.py` 등에 재시도 데코레이터 적용
- [ ] 스케줄러 잡 실패 시 알림 전송 로직 검토

#### [P2-4] 환경변수 및 시크릿 검증 강화
| 항목 | 내용 |
|------|------|
| **ID** | `sec-env-001` |
| **카테고리** | 🔒 보안 |
| **복잡도** | Low |
| **대상 파일** | `backend/core/config.py` |
| **Evidence** | 필수 환경변수 누락 시 런타임에 에러 발생 가능성 |
| **Origin** | manual-idea |
| **리스크 레벨** | **Low** |
| **관련 평가** | security |

- **현재 상태:** `.env` 파일 의존도가 높으나 로딩 시 검증이 느슨함.
- **개선 내용:** `pydantic-settings`를 활용하거나 시작 시점에 필수 키 존재 여부를 엄격히 체크합니다.

**Definition of Done:**
- [ ] `BackendSettings` 클래스에 필수 필드 검증 로직 확인/강화
<!-- AUTO-IMPROVEMENT-LIST-END -->

---

## 3. 신규 기능 제안 (P3)

<!-- AUTO-FEATURE-LIST-START -->
### 🟢 제안 (P3) - 신규 기능 및 편의성

#### [P3-1] 구조화된 로깅 시스템 도입
| 항목 | 내용 |
|------|------|
| **ID** | `feat-logger-001` |
| **카테고리** | ✨ 기능 / ⚙️ 운영 |
| **복잡도** | Low |
| **대상 파일** | `backend/core/logger.py` (신규) |
| **Evidence** | 현재 `alarm_process.log` 등 단순 텍스트 파일 로깅 사용 중 |

- **목적:** 로그를 JSON 포맷으로 남겨 추후 검색 및 분석(ELK, CloudWatch 등)이 용이하게 함.
- **내용:** `structlog` 또는 표준 `logging`의 JSON Formatter를 도입하여 Request ID, User ID 등을 포함한 컨텍스트 로깅 구현.

#### [P3-2] 대시보드 다국어(i18n) 통합 및 한글화 완성
| 항목 | 내용 |
|------|------|
| **ID** | `feat-dashboard-i18n-001` |
| **카테고리** | ✨ 기능 / 🧹 UI |
| **복잡도** | Low |
| **대상 파일** | `frontend/components/*.tsx` |
| **Evidence** | 일부 컴포넌트에 하드코딩된 영문 텍스트 잔존 ("Total P&L" 등) |

- **목적:** 사용자 경험 일관성을 위해 모든 UI 텍스트를 한국어로 통일.
- **내용:** `i18next` 도입 또는 상수 파일을 통한 텍스트 관리로 하드코딩 제거 및 한국어 적용.

<!-- AUTO-FEATURE-LIST-END -->

---

## 4. 코드 품질 및 성능 최적화 (OPT)

<!-- AUTO-OPTIMIZATION-START -->
### 🚀 코드 및 성능 최적화 (OPT)

#### 일반 분석 (General Analysis)
- **프론트엔드 로딩:** 대시보드 진입 시 자산, 뉴스, 알림 API가 개별적으로 호출되어 초기 렌더링이 튀는 현상(Waterfall) 발생 가능.
- **번들 사이즈:** `lucide-react` 등의 아이콘 패키지가 트리쉐이킹 되지 않고 통째로 포함되었는지 확인 필요.
- **데이터 쿼리:** DuckDB 쿼리 시 불필요한 컬럼까지 전체 조회(`SELECT *`)하는 패턴 다수.

#### [OPT-1] 대시보드 데이터 로딩 최적화
| 항목 | 내용 |
|------|------|
| **ID** | `opt-dashboard-Data-001` |
| **카테고리** | 🚀 성능 튜닝 |
| **영향 범위** | Frontend UX |
| **대상 파일** | `frontend/hooks/usePortfolio.ts`, `backend/routers/dashboard.py` |

- **현재 상태:** 클라이언트가 `useAsset`, `useNews`, `useAlarm` 등 여러 훅을 통해 개별적으로 데이터를 요청함.
- **최적화 내용:**
  1. **Backend:** `/api/dashboard/summary` 통합 엔드포인트 생성 (필수 요약 데이터 한 번에 반환).
  2. **Frontend:** 초기 로딩 시 통합 API를 호출하여 Layout Shift 방지.
- **예상 효과:** 초기 로딩 요청 수 감소 (N -> 1), 화면 깜빡임 최소화.
- **측정 지표:** Network 탭의 대시보드 로딩 시 API 호출 횟수 및 Total Blocking Time (TBT).
<!-- AUTO-OPTIMIZATION-END -->
