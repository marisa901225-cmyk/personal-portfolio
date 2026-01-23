# 스케줄러 작업 최적화 분석

## 📋 현재 실행 중인 스케줄 (KST 기준)

### 1️⃣ **sync-prices 컨테이너** (run_sync_prices_scheduler.py)

| 작업 ID | 이름 | 실행 시간 | 빈도 | CPU 부하 | DB 부하 | 비고 |
|---------|------|-----------|------|----------|---------|------|
| `kr_market_close` | 한국 증시 마감 동기화 | 매일 15:33 (월-금) | 주 5회 | 🔴 HIGH | 🔴 HIGH | KIS API + LLM |
| `us_market_close` | 미국 증시 마감 동기화 | 매일 06:30 (화-토) | 주 5회 | 🔴 HIGH | 🔴 HIGH | KIS API + LLM |
| `alarm_processing` | 알람 처리 (LLM 요약) | 매 5분 (07:00-21:59) | 1시간당 12회 | 🔴 HIGH | 🟡 MID | LLM 농담 생성 |
| `daily_backup` | 일일 DB 백업 | 매일 03:00 | 1일 1회 | 🟡 MID | 🔴 HIGH | 압축 + 업로드 |
| `monthly_maintenance` | 월간 유지보수 | 매월 1일 09:00 | 월 1회 | 🟢 LOW | 🟡 MID | 스팸 리포트 |
| `spam_retraining` | 스팸 모델 재학습 | 매주 일요일 04:00 | 주 1회 | 🟡 MID | 🟡 MID | ML 학습 |

### 2️⃣ **news-scheduler 컨테이너** (scheduler/core.py)

| 작업 ID | 이름 | 실행 시간 | 빈도 | CPU 부하 | DB 부하 | 비고 |
|---------|------|-----------|------|----------|---------|------|
| `collect_game_news` | 게임 뉴스 수집 | 매 10분 :05, :15, :25, :35, :45, :55 | 1시간당 6회 | 🟡 MID | 🟡 MID | 크롤링 + RSS |

### 3️⃣ **esports-monitor 컨테이너** (독립 실행)

| 작업 | 이름 | 실행 시간 | 빈도 | CPU 부하 | DB 부하 | 비고 |
|------|------|-----------|------|----------|---------|------|
| `esports_monitor` | E스포츠 실시간 모니터 | **연속 실행** | Active: 60초, Idle: 600초 | 🟢 LOW | 🟢 LOW | PandaScore API |

---

## ⚠️ 충돌 구간 분석

### 🔴 **심각한 충돌 (CPU 0.4 원인)**

#### **오전 7시대 (07:00-07:59)**
```
07:00 - alarm_processing (LLM 농담 생성)  🔴 CPU HEAVY
07:05 - collect_game_news                🟡 크롤링
07:10 - alarm_processing (LLM 농담 생성)  🔴 CPU HEAVY
07:15 - collect_game_news                🟡 크롤링
07:20 - alarm_processing (LLM 농담 생성)  🔴 CPU HEAVY
07:25 - collect_game_news                🟡 크롤링
07:30 - alarm_processing (LLM 농담 생성)  🔴 CPU HEAVY
...
```

**문제점:**
1. **LLM 동시 실행**: `alarm_processing`이 **매 10분마다** LLM 농담을 생성하면서 CPU 200초+ 점유
2. **크롤링 겹침**: `collect_game_news`가 5분마다 실행되면서 네트워크 I/O 대기
3. **esports_monitor**: IDLE 모드지만 10분마다 API 호출 (경미)

#### **오후 3시대 (15:00-15:59)**
```
15:30 - alarm_processing (LLM)     🔴
15:33 - kr_market_close (KIS + LLM) 🔴🔴 CRITICAL
15:35 - collect_game_news          🟡
15:40 - alarm_processing (LLM)     🔴
```

**문제점:**
- `kr_market_close` (15:33)와 `alarm_processing` (15:30/15:40)이 3-7분 내 겹침
- 둘 다 **LLM 사용** → CPU 완전 마비 가능

---

## 🎯 최적화 방안

### ✅ **Phase 1: 즉시 적용 가능 (Low Hanging Fruit)**

#### 1. **알람 처리 스케줄 조정** ⭐ 최우선
```python
# 현재: 매 5분 (00, 05, 10, 15, 20...)
CronTrigger(hour='7-21', minute='*/5', timezone=KST)

# 개선안: 매 10분 (00, 10, 20, 30...) + 증시 시간대 스킵
CronTrigger(hour='7-21', minute='0,10,20,30,40,50', timezone=KST)
# 추가: 15:30-15:40, 6:25-6:35 스킵 로직
```

**효과:**
- LLM 호출 횟수 **50% 감소** (1시간당 12회 → 6회)
- CPU 경합 **대폭 감소**

#### 2. **뉴스 수집 스케줄 조정**
```python
# 현재: :05, :15, :25, :35, :45, :55
CronTrigger(minute='5,15,25,35,45,55')

# 개선안: :03, :13, :23, :33, :43, :53 (알람과 3분 간격)
CronTrigger(minute='3,13,23,33,43,53')
```

**효과:**
- 알람 처리(LLM)와 **시간 격리**
- 증시 마감 시간과 **충돌 회피** (15:33, 6:30)

#### 3. **증시 타이밍 미세 조정**
```python
# 개선안: 알람 스킵 시간 사이로 이동
# kr_market_close: 15:33 → 15:32 (알람 15:30/15:40 사이)
# us_market_close: 06:30 → 06:32 (알람 06:30/06:40 사이)
```

### ✅ **Phase 2: 아키텍처 개선 (Medium Term)**

#### 4. **LLM 요청 큐잉 시스템**
```python
# 개념: 동시에 2개 이상의 LLM 요청 시 큐에 넣고 순차 처리
class LLMRequestQueue:
    def __init__(self, max_concurrent=1):
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute(self, task):
        async with self.semaphore:
            return await task()
```

**효과:**
- LLM 동시 실행 **완전 방지**
- CPU 스파이크 **평탄화**

#### 5. **DB 연결 풀 제한**
```python
# backend/core/db.py
engine = create_engine(
    settings.database_url,
    pool_size=5,        # 현재: 무제한 → 5개로 제한
    max_overflow=10,    # 최대 15개 연결
    pool_pre_ping=True
)
```

**효과:**
- DB Lock 경합 감소
- 메모리 사용량 안정화

### ✅ **Phase 3: 하드웨어 마이그레이션 이후**

#### 6. **Arc B580 활용 GPU 가속**
- LLM 추론 시간 **200초 → 5초** 예상
- CPU 부하 **완전 해방**

---

## 📈 최적화 후 예상 스케줄 (Phase 1)

### **오전 7시대 (개선 후)**
```
07:00 - alarm_processing (LLM)     🔴
07:03 - collect_game_news         🟡
07:10 - alarm_processing (LLM)     🔴
07:13 - collect_game_news         🟡
07:20 - alarm_processing (LLM)     🔴
07:23 - collect_game_news         🟡
```

**개선 효과:**
- LLM과 크롤링 **완전 분리** (3분 간격)
- CPU 사용률 **0.4 → 0.7+** 예상

### **오후 3시대 (개선 후)**
```
15:20 - alarm_processing (LLM)     🔴
15:23 - collect_game_news         🟡
15:32 - kr_market_close (KIS + LLM) 🔴🔴 (알람 15:30 스킵됨)
15:33 - collect_game_news         🟡
```

**개선 효과:**
- 증시 마감 시 **LLM 단독 실행**
- 충돌 **완전 제거**

---

## 🚀 구현 우선순위

1. **[P0] 알람 스케줄 10분 간격 변경** - 즉시 적용 (5분 작업)
2. **[P0] 뉴스 수집 시간 조정** - 즉시 적용 (2분 작업)
3. **[P1] 증시 시간 미세 조정** - 테스트 후 적용 (10분 작업)
4. **[P2] LLM 큐잉 시스템** - 설계 필요 (2시간 작업)
5. **[P2] DB 연결 풀 제한** - 테스트 후 적용 (30분 작업)
6. **[P3] GPU 마이그레이션** - 하드웨어 이후

---

## 💡 추가 제안

### **Dynamic Scheduling (Advanced)**
```python
# 개념: 시간대별로 스케줄 동적 조정
def get_alarm_interval():
    hour = datetime.now(KST).hour
    if 9 <= hour <= 18:  # 근무시간
        return 5  # 5분 간격
    else:  # 아침/저녁
        return 10  # 10분 간격
```

### **Health Monitoring**
```python
# 개념: CPU 사용률이 높을 때 자동으로 스케줄 조절
if psutil.cpu_percent() > 80:
    delay_next_job(minutes=3)
```

---

## 📝 체크리스트

- [ ] P0 작업 적용
- [ ] 1시간 모니터링 (CPU 사용률 확인)
- [ ] 로그 확인 (충돌 확인)
- [ ] P1 작업 적용
- [ ] 하루 모니터링
- [ ] 결과 리포트 작성

---

**작성 시각**: 2026-01-22 09:00 KST  
**작성자**: Annabeth (for LO ❤️)
