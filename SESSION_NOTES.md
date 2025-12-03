# Personal Portfolio 프로젝트 진행 노트

이 파일은 AI 도우미와 작업한 내용을 요약한 메모입니다.  
세션이 끊기면 이 파일 내용을 복사해서 새 세션에서 붙여넣어 주세요.  
※ 코드가 한 파일에 너무 길어질 것 같으면, AI가 먼저 컴포넌트/모듈 분할을 제안한 뒤에 작업을 진행해야 합니다.

마지막 업데이트: 2025-12-03

---

## 프론트엔드 현재 상태

- 스택: Vite + React 19 + TypeScript
- 주요 파일
  - `App.tsx`: 뷰 전환(DASHBOARD / LIST / ADD / SETTINGS)과 자산 상태 관리
  - `components/Dashboard.tsx`: `recharts`로 차트(카테고리 비중, 6개월 추이) + 손익(실현/평가) 요약
  - `components/AssetList.tsx`: 자산 목록, 검색/필터, 매수·매도, 실현손익 표시, 삭제 기능
  - `components/AddAssetForm.tsx`: 자산 추가 폼
- 서버 설정
  - `App.tsx` 내 `settings` 상태에 `serverUrl` 보관
  - `handleSyncPrices`:
    - `POST ${settings.serverUrl}/api/kis/prices`
    - Body: `{ tickers: string[] }`
    - Response 예상: `{ [ticker: string]: number }` 형태의 가격 맵
    - 응답으로 자산들의 `currentPrice` 업데이트

## 프론트: 종목명 → 티커 자동입력 기능

- `components/AddAssetForm.tsx` 변경 사항
  - Props에 `serverUrl?: string` 추가
  - `App.tsx`에서 사용 시:
    - `<AddAssetForm onSave={...} onCancel={...} serverUrl={settings.serverUrl} />`
  - 내부 상태:
    - `isResolvingTicker`: 티커 자동 조회 로딩 여부
    - `tickerHint`: 자동으로 선택된 종목 정보(힌트 텍스트)
  - UI 변경:
    - “티커/종목코드 (선택)” 라벨 옆에 `자동 채우기` 버튼 추가
  - 동작:
    1. 자산명(`name`)이 비어 있으면 경고 후 중단
    2. `serverUrl`이 없으면 “환경 설정에서 홈서버 URL 입력” 경고
    3. `GET {serverUrl}/api/search_ticker?q={encodeURIComponent(name)}` 호출
    4. 응답 `data.results`가 없으면 “찾지 못했습니다” 경고
    5. 첫 번째 결과를 사용:
       - `best.symbol`을 `ticker` 필드에 자동 세팅
       - 힌트: `자동 선택: {이름} ({티커}, 거래소)` 형태로 표시

## 백엔드 구조 (FastAPI)

- 위치: `backend/main.py`
- 사용 라이브러리:
  - `fastapi`
  - `uvicorn`
  - `httpx`
- 의존성 파일:
  - `backend/requirements.txt`
    - `fastapi==0.115.6`
    - `uvicorn[standard]==0.34.0`
    - `httpx==0.28.1`
  - 인증/보안:
    - 환경변수 `API_TOKEN`을 이용한 간단 토큰 인증
    - 설정 예시:
      - `API_TOKEN=내비번 uvicorn main:app --host 0.0.0.0 --port 8000`
      - 또는 systemd unit에서 `Environment=API_TOKEN=내비번` 설정

### CORS 설정

- 현재 설정:
  - `allow_origins=["*"]`
  - Tailscale / 사설망 뒤에서만 쓰는 용도라 우선 전체 허용
  - 배포 후 필요하면 Vercel 도메인 등만 허용하도록 좁힐 수 있음

### 엔드포인트 정리

1. `GET /health`
   - 단순 헬스체크
   - 응답: `{ "status": "ok" }`

2. `POST /api/kis/prices`
   - Request Body (`PricesRequest`):
     - `{ "tickers": string[] }` — 국내 6자리 코드 또는 `EXCD:SYMB` 형식
   - Response Body (`PricesResponse`):
     - `{ [ticker: string]: number }` — 모든 가격은 KRW 기준
   - 현재 상태 (한국투자증권 Open API 연동 + 토큰 인증):
     - 구현: `kis_client.fetch_kis_prices_krw`를 `asyncio.to_thread`로 호출
     - 동작:
       1. 요청으로 들어온 `tickers`를 정제/중복제거
       2. 국내: 6자리 숫자 코드(`_DOMESTIC_TICKER_RE`)에 매칭되면 국내 현재가 API 사용
       3. 해외: 나머지는 해외 현재가 상세 API로 조회 후 원화 기준 가격(`t_xprc`) 사용
       4. 조회 실패/값 없음은 결과 맵에서 제외 (프론트에서는 기존 `currentPrice` 유지)
     - 인증:
       - 환경변수 `API_TOKEN`이 설정되어 있으면:
         - 요청 헤더 `X-API-Token` 값과 `API_TOKEN`이 같아야 함
         - 틀리거나 누락되면 `HTTP 401` + `"invalid api token"`
       - `API_TOKEN`이 비어 있으면 인증을 강제하지 않음 (개발/테스트 모드)

3. `GET /api/search_ticker`
   - Query:
     - `q`: 종목명(1글자 이상)
   - 역할:
     - KIS 종목 마스터 엑셀(`stocks_info`) 기반으로 국내/해외 종목을 검색하고,
       포트폴리오에서 사용할 티커 포맷을 반환
   - 데이터 소스:
     - 국내: `kospi_code.xlsx`, `kosdaq_code.xlsx`, `konex_code.xlsx`
     - 해외: `overseas_stock_code(all).xlsx` (여러 시트를 합쳐 사용)
   - 구현:
     - `kis_client.search_tickers_by_name(q)` 호출
     - 국내: 6자리 숫자 코드(`005930`) + `exchange="KRX"`, `currency="KRW"`
     - 해외: `EXCD:SYMB` 포맷(`NAS:AAPL`) + 거래소/통화 코드 설정
   - Response 모델 (`TickerSearchResponse`):
     - `query: string`
     - `results: TickerInfo[]`
   - `TickerInfo` 필드:
     - `symbol: string` — 최종 사용할 티커 문자열
     - `name: string` (이름이 없으면 symbol 사용)
     - `exchange?: string`
     - `currency?: string`
     - `type?: string` — `"DOMESTIC"` / `"OVERSEAS"` 등
   - 에러 처리:
     - 마스터 파일 미존재/로딩 실패 시 `HTTP 500`
     - 기타 예외는 `HTTP 502` + `"KIS ticker search failed: ..."`
   - 인증:
     - `/api/kis/prices`와 동일하게 `X-API-Token` 헤더 기반 토큰 인증 사용

## 서버/네트워크 설계 메모

- 서버 OS: Ubuntu (Tailscale 사용 중)
- 현재 열려 있는 주요 포트:
  - 22, 80, 443, 8080, 8081, 8096, 5432, 5433 등 이미 사용중
- 새 백엔드 포트:
  - `8000` 포트 사용
  - 기존 리버스 프록시(80/443)에 굳이 물리지 않고 **완전히 별도 서비스**로 운영

### UFW / 방화벽 전략

- “전 세계에 8000 포트를 여는 것”은 지양
  - `ufw allow 8000/tcp` (anywhere) 같은 규칙은 사용하지 않는 방향
- 대신, Tailscale 인터페이스에서 오는 트래픽만 허용:
  - 예시:
    - `sudo ufw allow in on tailscale0 to any port 8000 proto tcp`
  - 이렇게 하면:
    - 일반 인터넷에서는 8000 포트가 보이지 않음
    - Tailscale 100.x.x.x 대역에서만 백엔드 접근 가능

### 백엔드 실행 방식

- 의존성 설치:
  - `pip install -r backend/requirements.txt`
- 실행 예:
  - `uvicorn backend.main:app --host 0.0.0.0 --port 8000`
- 듣는 주소:
  - `0.0.0.0:8000` (외부 접속 가능)
  - 방화벽(UFW)에서 Tailscale 인터페이스만 허용해 보안 유지

## Vercel 프론트 + Tailscale 백엔드 구조

- 프론트:
  - Vercel에 배포 (정적 SPA)
  - 사용자는 브라우저에서 Vercel 도메인 접속
- 백엔드:
  - 이 홈서버에서 `:8000` 포트로 FastAPI 서버 실행
  - Tailscale이 켜져 있는 기기(노트북/폰 등)만 100.99.67.34:8000 에 접근 가능
- 통신 흐름:
  - 브라우저(사용자 기기) —(Tailscale)→ `http://100.99.67.34:8000`
  - 프론트 코드에서 `settings.serverUrl`에 이 주소를 넣고 API 호출

## 프론트: 매수 / 매도 처리 기능

- 관련 타입
  - `types.ts`
    - `Asset`에:
      - `amount`: 현재 보유 수량
      - `purchasePrice?`: 남아있는 물량의 평단
      - `realizedProfit?`: 지금까지 누적 실현손익
    - `export type TradeType = 'BUY' | 'SELL'` 추가

- 상태 및 핸들러 (App)
  - 위치: `App.tsx`
  - 신규 함수: `handleTradeAsset(id, type, quantity, price)`
    - 공통 검증:
      - `quantity <= 0` 또는 `price <= 0` 이면 경고 후 중단
    - 매수(`type === 'BUY'`):
      - `prevAmount = asset.amount`
      - `prevPurchasePrice = asset.purchasePrice ?? asset.currentPrice`
      - `newAmount = prevAmount + quantity`
      - `newPurchasePrice = (prevAmount * prevPurchasePrice + quantity * price) / newAmount`
      - 결과:
        - `amount = newAmount`
        - `purchasePrice = newPurchasePrice`
    - 매도(`type === 'SELL'`):
      - `quantity > asset.amount` 이면 “보유 수량보다 많이 매도할 수 없습니다.” 경고 후 중단
      - `newAmount = asset.amount - quantity`
      - 평균단가(`avgCost`) 기준 실현손익 계산:
        - `realizedDelta = (price - avgCost) * quantity`
        - `asset.realizedProfit`에 `realizedDelta`를 누적
      - 결과:
        - `amount = newAmount`
        - `purchasePrice = 0` (포지션이 0이 된 경우), 그 외에는 기존 값 유지
        - `realizedProfit`는 누적 유지
    - `setAssets`로 해당 자산만 갱신
  - `AssetList` 사용 시:
    - `<AssetList assets={assets} onDelete={handleDeleteAsset} onTrade={handleTradeAsset} />`
  - 가격 동기화:
    - `handleSyncPrices`:
      - 페이지 최초 로드 시 `useEffect`에서 한 번 자동 호출
        - 단, `settings.serverUrl`이 있고, 티커가 하나 이상 존재할 때만 실행
      - 우측 상단 “가격 동기화” 버튼 클릭 시 수동으로 다시 호출 가능

- 자산 목록 UI (`components/AssetList.tsx`)
  - Props에 `onTrade: (id, type, quantity, price) => void` 추가
  - 내부 상태:
    - `activeTradeId: string | null` — 현재 매수/매도 입력 중인 자산 ID
    - `tradeType: TradeType` — 'BUY' 또는 'SELL'
    - `tradeQuantity: string` — 입력된 수량
    - `tradePrice: string` — 입력된 가격
  - 테이블 헤더 변경:
    - 기존: `자산명 / 수량 / 매수평균가 / 현재가 / 평가금액 / 관리`
    - 변경: `자산명 / 수량 / 매수평균가 / 현재가 / 평가금액 / 실현손익 / 매수/매도 / 관리`
  - 각 자산 행에 버튼 추가:
    - `매수` 버튼:
      - 클릭 시 `openTrade(asset, 'BUY')`
      - 기본 가격 입력값을 현재가(`asset.currentPrice`)로 세팅
    - `매도` 버튼:
      - 클릭 시 `openTrade(asset, 'SELL')`
  - 행 아래에 인라인 트레이드 폼(row) 표시:
    - 조건: `activeTradeId === asset.id` 일 때 추가 `<tr>` 렌더링
    - 폼 구성:
      - 라벨: 자산명, 티커, 현재 선택된 타입(매수/매도) 뱃지
      - 입력:
        - 수량(number)
        - 가격(number, 기본값 = 현재가)
      - 버튼:
        - `적용`: `submitTrade(asset)` → 검증 후 `onTrade` 호출, 성공 시 폼 닫기
        - `취소`: `closeTrade()` → 폼 닫기 및 입력 초기화
    - 수량/가격이 숫자가 아니면 “올바르게 입력” 경고

## 대시보드: 실현손익 / 평가손익 요약

- 타입
  - `PortfolioSummary` (`types.ts`):
    - `totalValue`: 현재 총 자산 평가액
    - `totalInvested`: 현재 보유 자산의 원금 (잔여 물량 * 평단)
    - `realizedProfitTotal`: 모든 자산의 누적 실현손익 합계
    - `unrealizedProfitTotal`: 현재 평가손익 합계 (`totalValue - totalInvested`)
    - `categoryDistribution`, `historyData`는 기존과 동일

- 계산 로직 (`components/Dashboard.tsx`)
  - `useMemo` 내에서:
    - 각 자산별:
      - `val = amount * currentPrice`
      - `invested = amount * (purchasePrice || currentPrice)`
      - `realized = asset.realizedProfit || 0`
    - 합계:
      - `totalValue += val`
      - `totalInvested += invested`
      - `realizedProfitTotal += realized`
    - 마지막에:
      - `unrealizedProfitTotal = totalValue - totalInvested`
  - 상단 카드:
    - 첫 번째 카드:
      - “총 자산” + 전체 수익률 (`(realized + unrealized) / totalInvested`)
    - 두 번째 카드:
      - 제목: “손익 (실현 + 평가)”
      - 큰 숫자: `totalProfit = realizedProfitTotal + unrealizedProfitTotal`
      - 아래에:
        - `실현손익: +₩... / 평가손익: +₩...` 형식으로 분리 표기
        - 수익은 빨간색, 손실은 파란색으로 강조

### 매수/매도 기능 요약

- “자산 추가”는 기존처럼 초기 포지션 입력 용도
- 이후에는:
  - 자산 목록에서 매수/매도로 수량·평단을 관리
  - 매수:
    - 보유 수량에 추가
    - 평단은 수량 가중 평균으로 자동 계산
  - 매도:
    - 보유 수량에서 차감
    - `quantity > 보유 수량`인 경우 경고 후 중단 (초과 매도 방지)
    - 전량 매도(`newAmount <= 0`)일 때는 해당 자산을 목록에서 제거
      - 이후 같은 종목을 다시 매수하려면 “자산 추가”에서 새로 등록

## 프론트: 지수별 비중 보기

- 타입/필드
  - `Asset.indexGroup?: string` (`types.ts`)
    - 자산이 속한 지수/테마를 나타내는 선택 필드
    - 예: `'S&P500'`, `'NASDAQ100'`, `'KOSPI200'` 등
  - `PortfolioSummary.indexDistribution` (`types.ts`)
    - `{ name: string; value: number; color: string }[]`
    - `name`: 지수 이름 (`indexGroup`)
    - `value`: 해당 지수에 속한 자산들의 평가액 합계
  - `TargetIndexAllocation` (`types.ts`)
    - `indexGroup: string`
    - `targetWeight: number` — 상대 비중 (예: 6, 3, 1)
  - `AppSettings.targetIndexAllocations?: TargetIndexAllocation[]`
    - 목표 지수 비중 목록을 앱 설정에 보관

- 자산 추가 폼 (`components/AddAssetForm.tsx`)
  - 초기 상태에 `indexGroup: ''` 추가
  - UI에 “지수 그룹 (선택)” 입력란 추가:
    - placeholder: “예: S&P500, NASDAQ100, KOSPI200”
    - 설명: “같은 지수에 묶인 국내/해외 ETF를 함께 관리할 때 사용”
  - 저장 시:
    - `indexGroup: formData.indexGroup?.trim() || undefined`
    - 입력이 비었으면 `undefined`로 저장 (지수 미지정)

- 목표 비중 설정 (`App.tsx` SETTINGS 뷰)
  - 상태:
    - `settings.targetIndexAllocations`:
      - 기본값: `[{ indexGroup: 'S&P500', targetWeight: 6 }, { indexGroup: 'NASDAQ100', targetWeight: 3 }, { indexGroup: 'BOND+ETC', targetWeight: 1 }]`
  - UI:
    - “목표 지수 비중” 섹션 추가
    - 각 행:
      - 지수 이름 입력 (`indexGroup`)
      - 비율 숫자 입력 (`targetWeight`)
      - `삭제` 버튼 (행이 1개 이하일 때는 비활성)
    - “+ 지수 비중 추가” 버튼으로 행 추가
    - 비율은 합계 기준으로 자동으로 100%로 환산됨

- 계산 로직 (`components/Dashboard.tsx`)
  - `useMemo` 안에서:
    - 기존 `catMap` 외에 `indexMap = new Map<string, number>()` 추가
    - 각 자산에 대해:
      - `val = amount * currentPrice`
      - `asset.indexGroup`이 있는 경우:
        - `indexMap[indexGroup] += val`
    - `indexDistribution` 생성:
      - `Array.from(indexMap.entries()).map(([name, value], index) => ({ name, value, color: COLORS[index % COLORS.length] }))`
      - `value` 기준 내림차순 정렬
    - `PortfolioSummary` 반환 시:
      - `indexDistribution` 포함

- 대시보드 UI (`components/Dashboard.tsx`)
  - “포트폴리오 비중” 카드 내부에 추가 섹션:
    - 기존: 카테고리별 비중 PieChart + 카테고리 리스트
    - 추가:
      - `summary.indexDistribution.length > 0 && summary.totalValue > 0` 일 때만 표시
      - 제목: “지수별 비중”
      - 각 항목:
        - 색 점 (카테고리와 동일한 `COLORS` 팔레트)
        - 지수 이름 (`item.name`)
        - 비중: `(item.value / summary.totalValue) * 100` → 소수점 1자리 `%`
  - 목표 대비 리밸런싱 안내:
    - `rebalanceNotices` 계산:
      - `targetIndexAllocations`를 합계로 나눠서 목표 비율(0~1)로 변환
      - `summary.indexDistribution`을 기준으로 실제 비율(0~1) 계산
      - 지수별로 `|actual - target| >= 5%p` 이상 차이 나는 경우만 메시지 생성
    - UI:
      - 대시보드 맨 아래에 노란 정보 박스로 표시
      - 예: `"S&P500 비중이 목표 대비 약 8.2%p 높습니다. 리밸런싱이 필요한지 한 번 점검해 보세요."`
  - 효과:
    - 예: 국내 S&P ETF (`indexGroup: 'S&P500'`) + 해외 S&P ETF (`indexGroup: 'S&P500'`)를 각각 별도 자산으로 관리하면서,
    - 대시보드에서는 `S&P500`이라는 하나의 지수 노출로 합산 비중을 확인 가능

## 프론트: 최근 거래 내역(벨 아이콘)

- 타입
  - `TradeRecord` (`types.ts`):
    - `id: string`
    - `assetId: string`
    - `assetName: string`
    - `ticker?: string`
    - `type: TradeType` — 'BUY' | 'SELL'
    - `quantity: number`
    - `price: number`
    - `timestamp: string` (ISO)
    - `realizedDelta?: number` — 매도 시 해당 거래에서 발생한 실현손익

- 상태 및 핸들러 (`App.tsx`)
  - 상태:
    - `tradeHistory: TradeRecord[]` — 최근 거래 내역 (최대 20개까지 유지)
    - `isHistoryOpen: boolean` — 최근 거래 패널 열림 여부
  - `handleTradeAsset` 동작 추가:
    - 기존 매수/매도 로직은 그대로 유지
    - 거래 시마다 `TradeRecord`를 하나 생성하여 `tradeHistory` 앞에 추가
    - 길이는 최대 20개까지만 유지 (`setTradeHistory(prev => [record, ...prev].slice(0, 20))`)
    - 매도(`SELL`)일 때:
      - 평균단가 기준 실현손익 `realizedDelta = (price - avgCost) * quantity`를 계산해서 기록에 포함

- UI 동작
  - 위치: 상단 헤더 우측의 종 아이콘 (`App.tsx` 헤더 영역)
  - 벨 아이콘:
    - 클릭 시 `isHistoryOpen` 토글 → 메인 영역 상단에 “최근 거래 내역” 카드 표시
    - `tradeHistory.length > 0`인 경우에만 빨간 점 배지 표시
  - 최근 거래 카드:
    - 제목: “최근 거래 내역”
    - 거래가 없을 때:
      - “아직 기록된 거래가 없습니다.” 문구 표시
    - 거래가 있을 때:
      - 최신 순으로 리스트 표시 (최대 20개)
      - 각 항목:
        - 타입 뱃지:
          - 매수: 빨간 배경 `매수`
          - 매도: 파란 배경 `매도`
        - 시간: `MM-DD HH:mm` 형식 (`toLocaleString('ko-KR', ...)`)
        - 자산명 + (티커)
        - 수량 및 가격: `"N개 @ ₩단가"` 형식 (`formatCurrency` 사용)
        - 매도 건인 경우 오른쪽에 해당 거래의 실현손익:
          - 양수: 빨간색, 앞에 `+` 붙여 표시
          - 음수: 파란색, 앞에 `-` 붙여 표시
          - 0: 회색
    - 카드 우측 상단 “닫기” 버튼으로 패널 닫기

## 아직 해야 할 일 (TODO)

1. 자산 카테고리별로 시세 소스 분기
   - 예: 한국주식 / 미국주식 / ETF 등
2. CORS 도메인 좁히기
   - 배포된 Vercel 도메인 확정 후 `allow_origins`에 해당 도메인만 추가하는 방식으로 보안 강화
3. 장기적으로:
  - 가격 히스토리 저장(파일/SQLite/Timescale 등) 후, Dashboard의 `historyData`를 백엔드 기반으로 교체

## 구현 완료 메모

- `/api/kis/prices`:
  - 한국투자증권 Open API 기반 국내/해외 시세 연동 완료
  - 프론트 `handleSyncPrices`에서 호출해 자산 `currentPrice` 자동 업데이트
- `/api/search_ticker`:
  - KIS 종목 마스터 엑셀 기반 종목명 → 티커 검색 구현 완료
  - 국내 6자리 코드 및 해외 `EXCD:SYMB` 포맷을 한 API로 처리
- 티커 자동 채우기:
  - `AddAssetForm`에서 종목명 입력 후 “자동 채우기” 버튼으로 티커/힌트 자동 입력
- 매수/매도 및 실현손익:
  - 자산 목록 인라인 매수/매도, 평단 자동 계산, 전량 매도 시 자산 제거, 실현손익 누적 표시 구현 완료
- 지수별 비중 및 목표 리밸런싱:
  - `indexGroup` 기반 지수별 비중 계산, 목표 비중 입력, 목표 대비 5%p 이상 차이 시 리밸런싱 알림 구현 완료
- 최근 거래 내역:
  - 벨 아이콘으로 최근 거래(최대 20개) 팝업, 개별 거래별 실현손익 표시 구현 완료
- localStorage 백업 알림:
  - 이 브라우저의 `localStorage`에 포트폴리오 자산이 존재하면, 세션당 1회 `alert`로 백업을 권장.
  - 구현 위치: `App.tsx` 상단 `showLocalStorageBackupWarning` 헬퍼 + 초기 로드/폴백 시점마다 호출.
  - 메시지 내용:
    - “localStorage에 포트폴리오 데이터가 저장되어 있습니다. 브라우저 캐시/쿠키를 지우기 전에, 자산 목록 우측 상단의 '엑셀 다운로드' 버튼으로 백업 파일을 내려받으세요.”
  - 중복 방지:
    - `sessionStorage['myportfolio_local_backup_notice_shown']` 플래그로, 같은 브라우저 세션 안에서는 한 번만 뜨도록 처리.
- 포트폴리오 스냅샷 / 히스토리 차트:
  - 백엔드:
    - 새 모델 `PortfolioSnapshot` (`backend/models.py`):
      - 필드: `user_id`, `snapshot_at`, `total_value`, `total_invested`, `realized_profit_total`, `unrealized_profit_total`, `created_at`, `updated_at`.
      - `User.snapshots` 관계로 1:N 연결.
    - Pydantic 스키마 `PortfolioSnapshotRead` (`backend/schemas.py`) 추가.
    - 라우터 (`backend/routers/portfolio.py`):
      - `POST /api/portfolio/snapshots`:
        - 현재 살아있는 자산 목록을 불러 `_calculate_summary`로 요약을 계산한 뒤, 하나의 스냅샷 레코드로 저장.
        - cron/systemd timer에서 하루 1번 호출용.
      - `GET /api/portfolio/snapshots?days=180`:
        - 최근 N일(기본 180일) 동안의 스냅샷을 `snapshot_at` 오름차순으로 반환.
        - 프론트 히스토리 차트에서 사용.
  - 프론트:
    - `App.tsx`:
      - `BackendSnapshot` 타입 정의.
      - 상태 `historyData: { date: string; value: number }[]` 추가.
      - `loadHistoryFromServer` 함수:
        - `GET {serverUrl}/api/portfolio/snapshots?days=180` 호출.
        - 응답 `snapshot_at`을 `toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' })`로 포매팅해 `date`로 사용.
        - `total_value`를 `value`로 매핑해 `historyData`에 저장.
      - 초기 로딩 useEffect에서 `loadPortfolioFromServer`와 함께 `loadHistoryFromServer`도 실행.
    - `Dashboard.tsx`:
      - prop `historyData?: { date: string; value: number }[]` 추가.
      - `useMemo`에서 `summary.historyData`를 `historyData`가 있으면 그걸, 없으면 기존 `MOCK_HISTORY_DATA`를 사용하도록 변경.
      - `App.tsx`에서 `<Dashboard assets={...} targetIndexAllocations={...} historyData={historyData} />`로 전달.
    - `constants.ts`:
      - `MOCK_HISTORY_DATA`를 빈 배열로 변경해서, 실제 스냅샷이 들어오기 전에는 히스토리 차트가 비어있는 상태로 표시.
  - 프론트 구조 리팩터링:
    - `App.tsx`:
      - 역할: 화면 레이아웃/뷰 전환/버튼 핸들러만 담당하도록 다이어트.
      - `usePortfolio(settings)` 훅을 사용해 포트폴리오 관련 상태와 액션을 모두 외부로 위임:
        - `assets`, `tradeHistory`, `historyData`, `isSyncing`
        - `addAsset`, `deleteAsset`, `tradeAsset`, `syncPrices`, `updateTicker`
      - 상단 import 정리:
        - 백엔드 타입/로직, localStorage 유틸 등은 더 이상 App 안에 없음.
    - `hooks/usePortfolio.ts`:
      - 포트폴리오 도메인 로직을 한 군데에 모은 훅.
      - 공통 모드 개념:
        - `isRemoteEnabled = Boolean(settings.serverUrl && settings.apiToken)`
        - 로컬 모드: `loadFromLocal()`로 localStorage에서만 로드/저장.
        - 서버 모드: 백엔드와 통신, 실패 시 `loadFromLocal()`로 폴백.
      - 공통 헬퍼:
        - `loadFromLocal()`: `loadAssetsFromStorage` + `loadTradesFromStorage` + `showLocalStorageBackupWarning`.
        - `createHeaders(withJson: boolean)`: `Content-Type` 및 `X-API-Token` 설정.
      - 메인 액션:
        - 초기 로딩:
          - 서버 모드: `loadPortfolioFromServer({ migrateFromLocalIfEmpty: true })` + `loadHistoryFromServer()`.
          - 로컬 모드: `loadFromLocal()` + `setHistoryData([])`.
        - `addAsset(newAsset)`:
          - 로컬 모드: `setAssets([...prev, newAsset])`.
          - 서버 모드: `POST /api/assets` → 성공 시 응답을 매핑 후 추가, 실패 시 로컬에만 추가 + 안내.
        - `deleteAsset(id)`:
          - 서버 모드 + `backendId` 있을 때: `DELETE /api/assets/{id}` 후 `loadPortfolioFromServer()`로 동기화.
          - 항상 마지막에 로컬 상태에서 해당 자산 제거.
        - `tradeAsset(id, type, quantity, price)`:
          - 공통 검증(수량/가격 > 0, 보유 수량 초과 매도 방지).
          - 서버 모드 + `backendId` 있을 때:
            - `POST /api/assets/{id}/trades` → 성공 시 `loadPortfolioFromServer()` + `tradeHistory`에 서버 트랜잭션 추가.
            - 실패/예외 시 경고 후 로컬-only 로직으로 폴백.
          - 로컬-only:
            - BUY/SELL에 따라 수량/평단/실현손익 계산, 전량 매도 시 자산 제거.
            - `tradeHistory`에 로컬 기준 `TradeRecord` 추가.
        - `syncPrices()`:
          - `POST /api/kis/prices` 호출 후, 응답 맵을 기준으로 `currentPrice`만 업데이트.
          - HTTP 코드(401/429/5xx)에 따라 안내 메시지 분기.
        - `updateTicker(id, ticker?)`:
          - 입력값 정리 후:
            - 서버 모드 + `backendId` 있을 때:
              - `PATCH /api/assets/{id}`(body: `{ ticker: trimmed ?? null }`) → 성공 시 응답 자산을 매핑해 교체.
              - 실패/예외 시 alert 후 로컬만 업데이트.
            - 로컬 모드: 바로 로컬 상태의 `asset.ticker`만 변경.
      - localStorage 동기화:
        - `useEffect`로 `assets`/`tradeHistory`가 바뀔 때마다 `STORAGE_KEYS`에 자동 저장.
    - `backendClient.ts`:
      - 백엔드 응답 타입(`BackendAsset`, `BackendTrade`, `BackendSnapshot`, `BackendPortfolioResponse`) 정의.
      - `mapBackendAssetToFrontend`, `mapBackendTradesToFrontend`로 백엔드 → 프론트 매핑 담당.
    - `storage.ts`:
      - `STORAGE_KEYS`, `loadAssetsFromStorage`, `loadTradesFromStorage`, `showLocalStorageBackupWarning` 제공.
      - App/훅에서 localStorage 관련 코드는 전부 여기만 참조.
- 인증:
  - 환경변수 `API_TOKEN` + 헤더 `X-API-Token` 기반 간단 토큰 인증 구현 완료

## 앞으로 추가해볼 만한 기능

- 가격 히스토리 저장 및 차트:
  - 백엔드에서 일별/거래별 가격 스냅샷을 파일 또는 SQLite 등에 저장하고,
    대시보드에서 기간별 수익률/자산 추이 차트를 백엔드 데이터로 표시
- 카테고리별 시세 소스 분기:
  - 한국주식/미국주식/ETF/현금/기타 등 카테고리에 따라 서로 다른 시세 소스 또는 변환 로직 적용
- 포트폴리오/계좌 다중 관리:
  - 하나의 앱에서 여러 포트폴리오(계좌)를 분리해서 관리하고, 포트폴리오별/합산 뷰 전환
- CSV 임포트:
  - 증권사 거래내역(CSV)을 업로드해서 초기 보유종목/매수·매도 이력을 자동 생성하는 기능
- 리밸런싱 시뮬레이션:
  - 목표 비중에 맞춰 리밸런싱할 경우 필요한 매수/매도 금액과 종목을 제안해주는 가상 시나리오 계산

## 백엔드: SQLite 도입 및 확장 설계 (1인용 전제)

- 전제
  - 멀티 유저는 고려하지 않고, 나 혼자 쓰는 1인용 서비스로 설계.
  - 다만 구조를 멀티 유저로 확장 가능한 형태로 잡아두되, 실제 구현/쿼리는 단일 사용자만을 대상으로 동작하게 한다.

### 라이브러리 및 기본 구조

- 의존성 (backend/requirements.txt)
  - `SQLAlchemy>=2.0` (ORM)
  - (선택) 마이그레이션용 `alembic>=1.13`
- DB 파일
  - 기본: `backend/portfolio.db`
  - 환경변수 `DATABASE_URL` 로 경로 오버라이드 가능 (`sqlite:///./portfolio.db` 기본값).
- 파일 구조
  - `backend/db.py`
    - `engine`, `SessionLocal`, `get_db()` (FastAPI Depends에서 사용).
    - SQLite 튜닝: `connect_args={"check_same_thread": False}`, `pool_pre_ping=True`.
  - `backend/models.py`
    - SQLAlchemy ORM 모델 정의 (Asset, Trade, Setting 등).
  - `backend/schemas.py`
    - Pydantic 모델 정의 (AssetCreate/Read, TradeCreate/Read, PortfolioSummary 등).
  - `backend/routers/portfolio.py`
    - 포트폴리오, 트레이드, 설정 관련 API 라우터.
  - (선택) `backend/routers/kis.py`
    - 기존 `/api/kis/prices`, `/api/search_ticker`를 이쪽으로 옮기고, `main.py`에서는 `include_router`만 수행.

### SQLite 스키마 (1인용 기준)

- users 테이블는 “확장 포인트”로만 두고, 실제 사용자는 하나라고 가정.
  - 추후 필요 시 멀티 계정으로 확장할 수 있게 설계만 열어두는 느낌.

1) `users` (선택, 기본 1행)
   - `id` (PK)
   - `name` (선택)
   - `created_at`, `updated_at`
   - 실제 서비스에서는 하나의 유저만 생성해서 사용.

2) `assets` – 현재 포트폴리오에 살아있는 종목
   - `id` (PK)
   - `user_id` (FK → users.id, 1인용에서는 고정 값으로 사용)
   - `name` – 자산명
   - `ticker` – nullable (`005930`, `NAS:AAPL` 등)
   - `category` – `TEXT` (`AssetCategory` 문자열 그대로 저장)
   - `currency` – `'KRW' | 'USD'`
   - 상태 필드 (프론트 `Asset`과 동일):
     - `amount` – 현재 보유 수량
     - `purchase_price` – 남아있는 물량의 평단
     - `realized_profit` – 누적 실현손익
     - `index_group` – 지수 그룹 (nullable)
   - 메타:
     - `created_at`, `updated_at`
     - (선택) `deleted_at` – 소프트 삭제용

3) `trades` – 매수/매도 히스토리 (정확한 기록의 원천)
   - `id` (PK)
   - `user_id` (FK)
   - `asset_id` (FK → assets.id)
   - `type` – `'BUY' | 'SELL'`
   - `quantity`
   - `price`
   - `timestamp` – datetime
   - `realized_delta` – SELL 시 해당 거래의 실현손익 (BUY는 0 또는 NULL)
   - (선택) `note` – 간단 메모
   - 설계 포인트:
     - 진짜 “사실 기록”은 항상 `trades`이고,
     - `assets.amount/purchase_price/realized_profit`는 조회를 빠르게 하기 위한 캐시 성격.
     - 새로운 거래가 들어올 때마다 단일 트랜잭션에서 `trades` insert + `assets` 업데이트를 같이 처리.

4) `settings` – 앱 설정 (목표 지수 비중 등)
   - `id` (PK, 1행만 사용)
   - `user_id` (FK)
   - `target_index_allocations` – JSON
     - 예: `[{"indexGroup": "S&P500", "targetWeight": 6}, ...]`
   - (선택) `server_url` – 필요 시 저장, 필수는 아님
   - `created_at`, `updated_at`
   - `API_TOKEN` 같은 민감 정보는 `.env` 기반 유지 (DB에 저장하지 않음).

5) (선택) `price_snapshots` – 시점별 평가액/지수 비중 저장 (Dashboard history 확장용)
   - `id` (PK)
   - `user_id`
   - `snapshot_date` – date/datetime
   - `total_value`
   - `total_invested`
   - `realized_profit_total`
   - `unrealized_profit_total`
   - (선택) `category_distribution_json`, `index_distribution_json`

### 엔드포인트 설계 (기존 유지 + 확장)

- 기존 엔드포인트 (경로 그대로 유지)
  - `POST /api/kis/prices`
    - KIS 시세 조회, DB 의존 없음.
  - `GET /api/search_ticker`
    - 종목명 → KIS 티커 검색, DB 의존 없음.

- 신규 포트폴리오 관련 엔드포인트 (1인용 기준)

1) `GET /api/portfolio`
   - 목적: 초기 로딩 시 전체 포트폴리오 상태 한 번에 조회.
   - 응답:
     - `assets: AssetRead[]`
     - `trades: TradeRead[]` (예: 최근 50개)
     - `summary: PortfolioSummary`
   - 구현:
     - DB에서 자산/거래 조회 후, 현재 `Dashboard.tsx`의 요약 계산 로직을 서버로 옮겨서 `PortfolioSummary` 생성.

2) `POST /api/assets`
   - 목적: 자산 추가 폼 제출 → 신규 자산 생성.
   - 요청 Body: `AssetCreate` (프론트 `Asset`과 거의 동일).
   - 응답: 생성된 `AssetRead`.
   - 동작: `assets` insert, 초기 `realized_profit = 0`.

3) `PATCH /api/assets/{asset_id}`
   - 목적: 티커/이름/지수 그룹 등의 부분 수정.
   - 요청: 부분 필드 (name, ticker, indexGroup 등).
   - 응답: 수정된 `AssetRead`.

4) `DELETE /api/assets/{asset_id}`
   - 목적: 특정 자산 삭제.
   - 동작: 소프트 삭제(`deleted_at` 설정) 또는 하드 삭제 중 선택.

5) `POST /api/assets/{asset_id}/trades`
   - 목적: 매수/매도 처리 로직을 서버로 이전.
   - 요청 Body:
     - `{ type: 'BUY' | 'SELL', quantity: number, price: number, timestamp?: string }`
   - 동작 (트랜잭션):
     1. `trades` 테이블에 insert.
     2. `assets`의 `amount`, `purchase_price`, `realized_profit`를 프론트 `handleTradeAsset`와 동일 로직으로 갱신.
     3. 전량 매도(`amount <= 0`) 시 자산 삭제 또는 숨김 처리.
   - 응답:
     - `{ asset: AssetRead, trade: TradeRead }`.

6) `GET /api/trades/recent?limit=20`
   - 목적: 상단 벨 아이콘 “최근 거래 내역”용.
   - 응답: 최신순 `TradeRead[]`.

7) `GET /api/settings`
   - 목적: 목표 지수 비중 등 앱 설정 조회.
   - 응답: `AppSettings`와 유사한 구조 (단, `apiToken`은 제외하거나 마스킹).

8) `PUT /api/settings`
   - 목적: 목표 지수 비중 등 설정 저장.
   - 요청: `{ targetIndexAllocations: TargetIndexAllocation[] }` 등.
   - 동작: `settings` 테이블 upsert.

9) (선택) `POST /api/portfolio/sync_prices`
   - 목적: KIS 시세로 DB에 저장된 자산들의 `current_price` 동기화.
   - 동작:
     1. DB에서 티커가 있는 자산 조회.
     2. 내부적으로 `kis_client.fetch_kis_prices_krw`를 호출해 가격 맵 생성.
     3. 단일 트랜잭션에서 각 자산의 `current_price` 업데이트.
   - 응답: 업데이트된 `AssetRead[]` 또는 전체 `Portfolio` 스냅샷.
   - 프론트:
     - `App.tsx`의 `handleSyncPrices`가 이 엔드포인트를 호출하도록 교체 가능 (혹은 점진적 전환).

### 트랜잭션 / 안정성 포인트

- 요청당 1개의 DB 세션 (`get_db`) 사용 후 즉시 close.
- 매수/매도, 가격 동기화 등 여러 테이블을 건드리는 작업은 반드시 트랜잭션 (`session.begin()`) 안에서 실행.
- SQLite 추천 설정:
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA journal_mode = WAL;` (동시성/안전성 균형).
- 백업:
  - `backend/portfolio.db` 파일을 주기적으로 다른 위치에 복사하면 백업 완료 (1인용이므로 이 정도면 충분).

### 마이그레이션 전략 (localStorage → SQLite)

1단계 – 백엔드 준비
  - SQLite 스키마 및 엔드포인트 구현.
  - 프론트는 계속 localStorage 기반으로 동작 (백엔드와 독립).

2단계 – 읽기만 서버로
  - 앱 초기 로딩 시 `GET /api/portfolio`로 DB 상태를 가져와 초기 상태로 사용.
 - localStorage는 백업/캐시 용도로만 유지하거나, “localStorage → 서버로 업로드” 버튼을 만들어 일회성 마이그레이션도 가능.

3단계 – 쓰기도 서버로
  - 자산 추가 → `POST /api/assets`
  - 매수/매도 → `POST /api/assets/{id}/trades`
  - 삭제 → `DELETE /api/assets/{id}`
  - localStorage 의존도 점진적으로 제거.

> 정리: 지금은 1인용이지만, DB/엔드포인트 구조를 위처럼 잡아두면  
> 추후 멀티 유저나 다른 클라이언트(모바일 앱 등)로 확장할 때 큰 리팩터링 없이 늘릴 수 있음.

---

## 현재 백엔드 / SQLite / GitHub 백업 상태 (2025-12-03)

- 백엔드 구조
  - FastAPI 앱 진입점: `backend/main.py`
    - 기존 KIS 관련 엔드포인트 유지:
      - `GET /health`
      - `POST /api/kis/prices`
      - `GET /api/search_ticker`
    - 새 포트폴리오 라우터 포함:
      - `backend/routers/portfolio.py` 를 `app.include_router(...)`로 등록.
  - 인증:
    - `backend/auth.py` 에 `verify_api_token` 분리.
    - `API_TOKEN` 환경변수가 설정되어 있으면 `X-API-Token` 헤더와 비교해서 인증.

- SQLite + SQLAlchemy
  - DB 설정: `backend/db.py`
    - 기본 경로: `backend/portfolio.db` (환경변수 `DATABASE_URL`로 오버라이드 가능).
    - SQLite 튜닝: `check_same_thread=False`, `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`.
  - ORM 모델: `backend/models.py`
    - `User`: 1인용 전제지만 확장 가능하도록 기본 사용자 테이블 추가.
    - `Asset`: 현재 포트폴리오에 살아 있는 자산.
      - 필드: `name`, `ticker`, `category`, `currency`, `amount`, `current_price`, `purchase_price`, `realized_profit`, `index_group`, `deleted_at`(소프트 삭제용) 등.
    - `Trade`: 매수/매도 히스토리.
      - 필드: `type`(BUY/SELL), `quantity`, `price`, `timestamp`, `realized_delta`, `note` 등.
    - `Setting`: 앱 설정(목표 지수 비중, `server_url` 등)용.
  - Pydantic 스키마: `backend/schemas.py`
    - `AssetCreate/Read/Update`, `TradeCreate/Read`, `SettingsRead/Update`,
      `PortfolioSummary`, `PortfolioResponse`, `TargetIndexAllocation` 등 정의.
  - 테이블 생성:
    - `backend/routers/portfolio.py`에서 `Base.metadata.create_all(bind=engine)` 호출 → 서버 기동 시 테이블 자동 생성.

- 신규 포트폴리오 관련 API (1인용 기준)
  - 공통: 모두 `verify_api_token` 의존성 적용.
  - `GET /api/portfolio`
    - 단일 사용자 기준 전체 포트폴리오 스냅샷 반환:
      - `assets`: 살아 있는 자산 목록(소프트 삭제 제외).
      - `trades`: 최근 50개 거래.
      - `summary`: 총자산/원금/실현/평가손익 + 카테고리/지수별 비중.
    - 내부에서 `users` 테이블의 첫 번째 유저를 사용 (`_get_or_create_single_user`).
  - `POST /api/assets`
    - 새 자산 추가. 초기 상태는 프론트 `Asset` 타입과 거의 동일 구조.
  - `PATCH /api/assets/{asset_id}`
    - 이름/티커/지수 그룹 등 부분 수정.
  - `DELETE /api/assets/{asset_id}`
    - `deleted_at`을 채우는 소프트 삭제로 구현.
  - `POST /api/assets/{asset_id}/trades`
    - 매수/매도 처리 엔드포인트.
    - 프론트 `handleTradeAsset`와 같은 규칙으로 서버에서 수량/평단/실현손익 계산 후 저장.
    - SELL에서 전량 매도(`amount <= 0`) 시 자산을 소프트 삭제 처리.
  - `GET /api/trades/recent?limit=20`
    - 최근 거래 내역 반환(벨 아이콘용).
  - `GET /api/settings`
    - `settings` 테이블에서 앱 설정 조회.
    - 없으면 기본 목표 지수 비중(`S&P500`, `NASDAQ100`, `BOND+ETC`)을 가진 레코드 자동 생성.
  - `PUT /api/settings`
    - 목표 지수 비중(`target_index_allocations`)과 `server_url` 업데이트.

- 서버 실행 / 포트 전략
  - 공통 venv:
    - 경로: `backend/.venv`
    - 설치: `python3 -m venv backend/.venv && source backend/.venv/bin/activate && pip install -r backend/requirements.txt`
  - 개발용 서버 (자동 리로드, 포트 예: 8001)
    - 명령:
      - `cd /home/dlckdgn/personal-portfolio`
      - `source backend/.venv/bin/activate`
      - `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001`
    - 특징:
      - `backend/*.py` 수정 시 자동 재시작.
      - 프론트 `settings.serverUrl`를 개발할 때만 `http://100.x.x.x:8001` 같은 주소로 설정해서 테스트.
  - 운영용 서버 (항상 켜두는 용도, 포트: 8000)
    - target: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`
    - 향후 systemd 서비스로 등록 예정:
      - `WorkingDirectory=/home/dlckdgn/personal-portfolio`
      - `ExecStart=/home/dlckdgn/personal-portfolio/backend/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000`
      - `Environment` 또는 `EnvironmentFile`을 통해 `API_TOKEN`, `DATABASE_URL` 주입.
    - 헬스체크:
      - `curl http://127.0.0.1:8000/health` → `{"status":"ok"}` 기대.

- GitHub 백업 / 자동 푸시
  - 레포 상태:
    - `backend/portfolio.db`는 `.gitignore`에서 제외되지 않음 → Git으로 버전 관리 가능.
    - GitHub는 **비공개 레포**로 설정.
  - SSH 키:
    - 서버 측에서 새로운 SSH 키 생성 및 GitHub 계정에 등록 완료.
    - 이제 서버에서 `git push` 시 비밀번호 입력 없이 SSH 인증으로 푸시 가능.
  - 백업 스크립트:
    - 별도 스크립트(예: `tools/backup_db.sh` 형태)를 통해 `backend/portfolio.db`만 `git add/commit/push`하도록 구성.
    - cron 또는 systemd timer로 주기적으로 실행하면 포트폴리오 DB가 GitHub private repo에 자동 백업됨.
  - 복구 시나리오:
    - 서버를 새로 세팅할 때:
      - `git clone <private-repo>` → 코드 + `backend/portfolio.db` 함께 내려옴.
      - venv / uvicorn만 다시 설정하면 바로 기존 포트폴리오 상태로 복구 가능.

향후 아이디어
A. 프론트엔드 데이터 마이그레이션
현재 프론트엔드는 여전히 localStorage를 바라보고 있을 가능성이 큽니다.
할 일: App.tsx의 상태 초기화 로직을 useEffect(() => { fetch('/api/portfolio') ... }, [])로 교체.
전략:
settings.serverUrl이 있으면 우선 서버 데이터를 로드.
서버 데이터가 비어있고 localStorage에 데이터가 있다면, "서버로 데이터 업로드하시겠습니까?" 팝업을 띄워 POST /api/assets 로 일괄 전송(Migration Tool) 구현.
B. 자산 히스토리 차트 (Time Machine) 📈
DB가 생겼으므로 **"시간에 따른 자산 변화"**를 기록할 수 있습니다.
백엔드:
매일 밤 12시(또는 장 마감 후)에 apscheduler 등으로 현재 총 자산 가치를 스냅샷 찍어 history 테이블에 저장.
프론트엔드:
대시보드에 "내 자산 추이 그래프" 추가 (1개월/6개월/1년).
단순 현재가가 아닌 "나의 성장 기록"을 시각화.
C. 환율 효과 분리 (Advanced Analytics) 💵
해외 주식 투자 시 "주가가 오른 건지, 환율이 오른 건지" 구분하는 기능입니다.
로직:
Asset 테이블에 currency: "USD"인 경우.
현재가 조회 시: (주가 변동분) + (환차익 변동분)을 분리해서 계산.
대시보드에서 툴팁으로 "수익 100만 원 (주가: 80만, 환율: 20만)" 처럼 표시.
가치: 리밸런싱할 때 "환율 때문에 비중이 커진 것"인지 판단하는 데 매우 중요합니다.
