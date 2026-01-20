# 🛠️ 프로젝트 개선 탐구 보고서 (Project Improvement Exploration Report)

이 보고서는 프로젝트에 적용되지 않은 **Pending 상태의 개선 항목**만을 다룹니다.

---

## 1. 개선 요약 (Overall Status)

<!-- AUTO-SUMMARY-START -->
현재 프로젝트는 기능적으로 안정적이나, 코드 품질과 장기적 유지보수성을 위해 몇 가지 기술적 부채를 해결해야 합니다. 아래는 식별된 보류 항목들의 분포입니다.

### 📊 우선순위 분포 (Priority Distribution)
| 우선순위 | 개수 |
|:---:|---:|
| P1 | 1 |
| P2 | 2 |
| P3 | 1 |
| OPT | 1 |

### 🗂️ 카테고리 분포 (Category Distribution)
| 카테고리 | 개수 | 대표 ID 예시 |
|---|---:|---|
| 🧪 테스트 | 1 | `test-coverage-frontend-001` |
| 🧹 코드 품질 | 1 | `code-quality-frontend-001` |
| 🏗️ 아키텍처 | 1 | `arch-backend-refactor-001` |
| ⚙️ 운영/로그 | 1 | `infra-logging-001` |
| 🚀 최적화 | 1 | `opt-simhash-cache-001` |

### 🔎 Origin 분포
| Origin | 개수 |
|---|---:|
| static-analysis | 5 |

### 🚨 Riks Level 분포
| Risk level | 개수 |
|---|---:|
| medium | 3 |
| low | 2 |

**우선순위 선정 근거:**
- **P1:** 프론트엔드의 테스트 부족은 회귀 버그 발생 위험이 높아 최우선으로 대응 필요.
- **P2:** 타입 안정성 및 비즈니스 로직 분리는 유지보수 비용을 낮추기 위해 중요.
- **P3/OPT:** 운영 편의성 및 성능 개선은 상대적으로 긴급도가 낮음.
<!-- AUTO-SUMMARY-END -->

---

## 2. 기능 개선 항목 (Functional Improvements)

<!-- AUTO-IMPROVEMENT-LIST-START -->
### 🔴 중요 (P1)

#### [P1-1] 프론트엔드 핵심 로직 테스트 추가
| 항목 | 내용 |
|------|------|
| **ID** | `test-coverage-frontend-001` |
| **카테고리** | 🧪 테스트 |
| **복잡도** | Medium |
| **대상 파일** | `frontend/src/shared/api/client/types.ts` 등 |
| **Evidence** | `package.json`: vitest 설정은 있으나 실제 비즈니스 로직 테스트 부족 |
| **Origin** | static-analysis |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | testCoverage |

- **현재 상태:** `vitest`가 설정되어 있으나, 주요 데이터 파싱이나 상태 관리 로직에 대한 단위 테스트가 부족함.
- **문제점:** 리팩토링이나 기능 추가 시 기존 로직이 깨지는 것을 감지하기 어려움.
- **영향:** 런타임 에러 발생 가능성 및 배포 후 장애 위험.
- **원인:** 초기 개발 시 빠른 기능 구현에 집중하여 테스트 작성이 후순위로 밀림.
- **개선 내용:** 주요 유틸리티 함수 및 API 클라이언트 로직에 대한 테스트 케이스 작성.
- **기대 효과:** 코드 안정성 확보 및 리팩토링 신뢰도 향상.

**Definition of Done:**
- [ ] 주요 로직에 대한 Unit Test 추가
- [ ] `npm run test` 통과 확인

---

### 🟡 중요 (P2)

#### [P2-1] 프론트엔드 타입 안정성 강화
| 항목 | 내용 |
|------|------|
| **ID** | `code-quality-frontend-001` |
| **카테고리** | 🧹 코드 품질 |
| **복잡도** | Low |
| **대상 파일** | `frontend/src/shared/api/client/types.ts` |
| **Evidence** | `types.ts`: `: any` 사용 감지됨 |
| **Origin** | static-analysis |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | codeQuality |

- **현재 상태:** 일부 타입 정의에서 `any`를 사용하여 TypeScript의 장점을 살리지 못하고 있음.
- **문제점:** 컴파일 타임에 타입 에러를 잡지 못하고 런타임 에러로 이어질 수 있음.
- **개선 내용:** `any`를 구체적인 인터페이스나 제네릭으로 대체.
- **기대 효과:** 런타임 안정성 향상 및 IDE 자동완성 지원 강화.

**Definition of Done:**
- [ ] `any` 타입을 구체적인 타입으로 변경
- [ ] 타입 체크 (`npm run typecheck`) 통과

#### [P2-2] 백엔드 라우터 로직 분리
| 항목 | 내용 |
|------|------|
| **ID** | `arch-backend-refactor-001` |
| **카테고리** | 🏗️ 아키텍처 |
| **복잡도** | Medium |
| **대상 파일** | `backend/routers/portfolio.py` |
| **Evidence** | `portfolio.py`: `get_portfolio` 라우터 함수 내에 쿼리 및 로직 혼재 |
| **Origin** | static-analysis |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | codeQuality |

- **현재 상태:** 라우터 함수가 DB 쿼리와 응답 조립 로직을 직접 수행하고 있음.
- **문제점:** 로직 재사용이 어렵고 테스트가 복잡해짐.
- **개선 내용:** 비즈니스 로직을 `services/portfolio_service.py` 등으로 완전히 이관하고 라우터는 호출만 담당.
- **기대 효과:** 코드 가독성 향상 및 단위 테스트 용이성 확보.

**Definition of Done:**
- [ ] 라우터 내 로직을 Service 계층으로 이동
- [ ] API 동작 동일성 검증
<!-- AUTO-IMPROVEMENT-LIST-END -->

---

## 3. 기능 추가 항목 (New Features)

<!-- AUTO-FEATURE-LIST-START -->
### 🟢 보통 (P3)

#### [P3-1] 에러 로그 구조화 및 모니터링 강화
| 항목 | 내용 |
|------|------|
| **ID** | `infra-logging-001` |
| **카테고리** | ⚙️ 운영/로그 |
| **복잡도** | Low |
| **대상 파일** | `backend/core/logging_config.py` (신규 또는 수정) |
| **Evidence** | `main.py`: 기본 logging 설정만 존재, 구조화된 로그 부족 |
| **Origin** | manual-idea |
| **리스크 레벨** | low |
| **관련 평가 카테고리** | productionReadiness |

- **현재 상태:** 텍스트 기반의 단순 로그만 출력됨.
- **개선 내용:** JSON 포맷 로그를 도입하여 검색 및 분석이 용이하도록 개선.
- **기대 효과:** 장애 발생 시 원인 분석 시간 단축.

**Definition of Done:**
- [ ] 로그 포맷터를 JSON 구조로 변경 또는 옵션 추가
- [ ] 주요 에러 상황에서 Context(Request ID 등) 포함 확인
<!-- AUTO-FEATURE-LIST-END -->

---

## 4. 코드 최적화 (Optimization)

<!-- AUTO-OPTIMIZATION-START -->
- **분석 결과:**
  - SimHash 알고리즘이 매번 계산될 수 있어 캐싱이 유리함.
  - 반복적인 문자열 처리 구간 존재.

### 🚀 코드 최적화 (OPT-1)

| 항목 | 내용 |
|------|------|
| **ID** | `opt-simhash-cache-001` |
| **카테고리** | 🚀 코드 최적화 |
| **영향 범위** | 성능 |
| **대상 파일** | `backend/services/news/deduplication.py` (가정) |

- **현재 상태:** 뉴스 기사 중복 제거 시 SimHash 계산 비용이 발생.
- **최적화 내용:** 계산된 SimHash 값을 메모리, 또는 DB에 캐싱하여 재계산 방지 (LRU Cache 등 적용).
- **예상 효과:** 대량의 뉴스 처리 시 CPU 사용량 감소 및 처리 속도 향상.
- **측정 지표:** 뉴스 처리 배치 작업 소요 시간.
<!-- AUTO-OPTIMIZATION-END -->

---

## 5. 세션 로그 (Session Log)

<!-- AUTO-SESSION-LOG-START -->
### 2026-01-20 (자동 분석 세션)
- 분석 내용: 코드베이스 스캔을 통해 미적용 개선 항목을 확정함. 식별된 미적용 항목 수: 6 (P1:1, P2:2, P3:1, OPT:2).
- 새로 발견된 항목: 없음 (현재 목록은 static-analysis 기반 기존 식별 항목 중심).
- 권장 조치: P1 우선 실행(프론트엔드 핵심 테스트), 이어서 P2 항목 적용(타입 안정성·라우터 분리).
<!-- AUTO-SESSION-LOG-END -->
