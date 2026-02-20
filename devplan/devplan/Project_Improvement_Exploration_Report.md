# 🛠️ 프로젝트 개선 탐구 보고서 (Project Improvement Exploration Report)

이 보고서는 프로젝트에 적용되지 않은 **Pending 상태의 개선 항목**만을 다룹니다.

---

## 1. 개선 요약 (Overall Status)

<!-- AUTO-SUMMARY-START -->
현재 프로젝트는 **코드 품질** 측면에서 매우 우수하지만, **테스트 관리**와 **레거시 코드 정리**에 집중할 필요가 있습니다. 제미나이(Gemini) 등 실험용으로 작성된 코드들이 백엔드 테스트 수집을 방해하고 있으며, 리팩토링 과정에서 변경된 모듈 경로가 반영되지 않은 테스트들이 존재합니다. 따라서 이번 개선 주기는 **핵심 로직 테스트 가동**과 **불필요한 코드 제거**를 중심으로 진행합니다.

### 📊 우선순위 분포 (Priority Distribution)
| 우선순위 | 개수 |
|:---:|---:|
| **P1** | 1 |
| **P2** | 2 |
| **P3** | 1 |
| **OPT** | 1 |

### 🗂️ 카테고리 분포 (Category Distribution)
| 카테고리 | 개수 | 대표 ID 예시 |
|---|---:|---|
| 🧪 테스트 | 1 | `test-backend-env-001` |
| 🛡️ 안정성 | 1 | `feat-error-boundary-001` |
| 🧹 코드 품질 | 1 | `code-cleanup-legacy-001` |
| ✨ 기능 추가 | 1 | `feat-telegram-template-001` |
| 🚀 최적화 | 1 | `opt-duckdb-query-001` |

### 🔎 Origin 분포 (Pending Only)
| Origin | 개수 |
|---|---:|
| test-failure | 2 |
| manual-idea | 3 |
| static-analysis | 0 |

### 🚨 Risk Level 분포 (Pending Only)
| Risk level | 개수 |
|---|---:|
| high | 1 |
| medium | 3 |
| low | 1 |

**우선순위 선정 근거:**
- **P1 (High Risk):** 테스트 수집 에러 해결과 잘못된 모듈 경로 수정을 통해 전체 테스트 파이프라인을 복구합니다.
- **P2 (Medium Risk):** 실험용 코드 정리와 에러 처리 강화를 통해 시스템의 순수성을 유지합니다.
<!-- AUTO-SUMMARY-END -->

---

## 2. 상세 개선 항목 (Detailed Improvement Items)

<!-- AUTO-IMPROVEMENT-LIST-START -->
### 🔴 중요 (P1)

#### [P1-1] 백엔드 테스트 환경 정렬 및 수집 에러 해결
| 항목 | 내용 |
|------|------|
| **ID** | `test-backend-env-001` |
| **카테고리** | 🧪 테스트 |
| **복잡도** | Medium |
| **대상 파일** | `backend/tests/`, `backend/pytest.ini`, `devplan/test_db/test.db` |
| **Evidence** | 리팩토링으로 인한 파일명 변경/삭제로 테스트 경로 불일치, `pytest --collect-only` 시 에러 발생 |
| **Origin** | test-failure |
| **리스크 레벨** | high |
| **관련 평가 카테고리** | testCoverage |

- **현재 상태:** 리팩토링 과정에서 백엔드 파일명이 변경되거나 삭제되었으나, 테스트 코드가 이를 반영하지 못해 Import 에러가 발생합니다. 또한 테스트 DB가 `devplan/test_db/test.db`에 위치하도록 설정이 필요합니다.
- **문제점:** 전체 테스트 수집이 불가능하여 개발 중인 기능의 안정성을 검증할 수 없습니다.
- **개선 내용:** 
    1. 테스트 코드 내의 임포트 경로를 현재 백엔드 구조(`runners/` 폴더 등)에 맞게 전수 수정.
    2. 삭제된 파일에 대한 테스트 제거 또는 업데이트.
    3. `pytest` 실행 시 `DATABASE_URL`이 `devplan/test_db/test.db`를 바라보도록 환경 설정 추가.
- **기대 효과:** 백엔드와 테스트 환경의 완벽한 동기화 및 전수 테스트 가동.

**Definition of Done:**
- [ ] `pytest` 실행 시 `DATABASE_URL`이 `devplan/test_db/test.db`로 정상 연결됨
- [ ] 수집(Collection) 에러 0건 및 핵심 서비스 테스트 통과

### 🟡 중요 (P2)

#### [P2-1] 프론트엔드 에러 바운더리(Error Boundary) 및 전역 에러 처리
| 항목 | 내용 |
|------|------|
| **ID** | `feat-error-boundary-001` |
| **카테고리** | 🛡️ 안정성 |
| **복잡도** | Low |
| **대상 파일** | `frontend/src/app/App.tsx`, `frontend/src/shared/ui/ErrorBoundary.tsx` |
| **Evidence** | 현재 렌더링 에러 발생 시 전체 페이지가 멈추는 현상 발생 가능 |
| **Origin** | manual-idea |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | stability |

- **현재 상태:** 특정 컴포넌트의 렌더링 실패가 전체 애플리케이션의 중단(White Screen)으로 이어질 수 있습니다.
- **개선 내용:** React `ErrorBoundary`를 최상위 및 기능 단위로 적용하고, 사용자 친화적인 폴백 UI 제공.
- **기대 효과:** 앱의 가용성 증대 및 안정적인 사용자 경험 제공.

**Definition of Done:**
- [ ] 전역 `ErrorBoundary` 적용 완료 및 테스트 성공

#### [P2-2] 실험용/레거시 코드 정리 (Legacy Cleanup)
| 항목 | 내용 |
|------|------|
| **ID** | `code-cleanup-legacy-001` |
| **카테고리** | 🧹 코드 품질 |
| **복잡도** | Low |
| **대상 파일** | `backend/scripts/test_gemini_*`, `backend/scripts/test_global_running.py` |
| **Evidence** | `test_gemini_esports.py` 등 현재 시스템에서 사용하지 않는 실험용 코드 방치 |
| **Origin** | manual-idea |
| **리스크 레벨** | medium |
| **관련 평가 카테고리** | maintainability |

- **현재 상태:** 프로젝트 초기 실험용으로 작성된 제미나이(Gemini) 연동 코드들이 프로젝트 공식 스크립트 디렉토리에 섞여 있습니다.
- **문제점:** 전체 테스트 실행 시 의존성(API Key) 문제로 에러를 유발하며, 유지보수 시 혼란을 줍니다.
- **개선 내용:** 사용하지 않는 실험용 코드를 `legacy/` 폴더로 이동하거나 삭제 처리.
- **기대 효과:** 코드베이스 경량화 및 테스트 신뢰도 향상.

**Definition of Done:**
- [ ] 불필요한 실험용 스크립트 정리 완료
<!-- AUTO-IMPROVEMENT-LIST-END -->

---

## 3. 기능 추가 항목 (New Features)

<!-- AUTO-FEATURE-LIST-START -->
### 🟢 보통 (P3)

#### [P3-1] 텔레그램 알림 템플릿 다양화 및 가독성 개선
| 항목 | 내용 |
|------|------|
| **ID** | `feat-telegram-template-001` |
| **카테고리** | ✨ 기능 추가 |
| **복잡도** | Low |
| **대상 파일** | `backend/services/alarm/alarm_service.py`, `backend/prompts/` |
| **Evidence** | 현재 알림 메시지가 텍스트 위주로 구성되어 시각적 구분이 어려움 |
| **Origin** | manual-idea |
| **리스크 레벨** | low |
| **관련 평가 카테고리** | usability |

- **현재 상태:** 모든 텔레그램 알림이 단일 포맷의 텍스트로 발송됩니다.
- **개선 내용:** 이모지 활용 강화 및 뉴스/지출/일반 알림별 맞춤형 템플릿 도입.
- **기대 효과:** 중요한 알림의 가독성 및 사용자 인식률 향상.
<!-- AUTO-FEATURE-LIST-END -->

---

## 4. 코드 최적화 (Optimization)

<!-- AUTO-OPTIMIZATION-START -->
- **분석 결과 (General Analysis):**
  - DuckDB 쿼리 집계 시 대량의 뉴스 데이터를 매번 스캔하여 자원 낭비 발생.
  - API 응답 속도 최적화를 위한 데이터 캐싱 레이어 부재.

### 🚀 코드 최적화 (OPT-1)

| 항목 | 내용 |
|------|------|
| **ID** | `opt-duckdb-query-001` |
| **카테고리** | 🚀 코드 최적화 |
| **영향 범위** | 성능 |
| **대상 파일** | `backend/services/news/duckdb_refine_queries.py` |

- **현재 상태:** 뉴스 대시보드 조회 시 원본 테이블(6,600+ 건)을 직접 집계하여 지연이 발생할 수 있습니다.
- **최적화 내용:** 요약 테이블(Summary Table)을 생성하고 스케줄러를 통해 정기적으로 업데이트하여 조회 시 스캔 범위 최소화.
- **예상 효과:** 대시보드 뉴스 통계 조회 속도 3배 이상 향상.
- **측정 지표:** API 응답 지연 시간 (Latency).
<!-- AUTO-OPTIMIZATION-END -->
