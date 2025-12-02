# Personal Portfolio 프로젝트 진행 노트

이 파일은 AI 도우미와 작업한 내용을 요약한 메모입니다.  
세션이 끊기면 이 파일 내용을 복사해서 새 세션에서 붙여넣어 주세요.  
※ 코드가 한 파일에 너무 길어질 것 같으면, AI가 먼저 컴포넌트/모듈 분할을 제안한 뒤에 작업을 진행해야 합니다.

마지막 업데이트: 2025-12-02

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
    - `POST ${settings.serverUrl}/api/prices`
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

2. `POST /api/prices`
   - Request Body (`PricesRequest`):
     - `{ "tickers": string[] }`
   - Response Body (`PricesResponse`):
     - `{ [ticker: string]: number }`
   - 현재 상태 (Yahoo Finance 연동 + 토큰 인증):
     - 엔드포인트: `https://query1.finance.yahoo.com/v7/finance/quote`
     - 동작:
       1. 요청으로 들어온 `tickers`를 정제/중복제거 후, `symbols` 파라미터로 한 번에 조회
       2. 각 티커의 `regularMarketPrice`, `currency`를 사용해 현재가 계산
       3. `currency === 'USD'` 인 티커가 하나라도 있으면:
          - `USDKRW=X`를 같은 Quote API로 조회하여 원/달러 환율(`regularMarketPrice`)을 가져옴
          - 해당 환율을 곱해서 KRW 기준 가격으로 변환
       4. 그 외 통화(기본적으로 KRW)는 별도 변환 없이 그대로 사용
     - 결과:
       - 모든 티커의 가격을 **KRW 기준 숫자**로 프론트에 전달
       - Yahoo에서 찾지 못한 티커나 가격이 없는 경우는 맵에서 빠지고, 프론트에서는 기존 `currentPrice`를 유지
     - 인증:
       - 환경변수 `API_TOKEN`이 설정되어 있으면:
         - 요청 헤더 `X-API-Token` 값과 `API_TOKEN`이 같아야 함
         - 틀리거나 누락되면 `HTTP 401` + `"invalid api token"`
       - `API_TOKEN`이 비어 있으면 인증을 강제하지 않음 (개발/테스트 모드)

3. `GET /api/search_ticker`
   - Query:
     - `q`: 종목명(1글자 이상)
   - 역할:
     - Yahoo Finance 검색 API를 이용해 종목명으로 티커 검색
   - 외부 API:
     - `https://query1.finance.yahoo.com/v1/finance/search`
     - 파라미터: `q`, `quotesCount=5`, `newsCount=0`
   - Response 모델 (`TickerSearchResponse`):
     - `query: string`
     - `results: TickerInfo[]`
   - `TickerInfo` 필드:
     - `symbol: string`
     - `name: string` (shortname/longname/없으면 symbol)
     - `exchange?: string`
     - `currency?: string`
     - `type?: string`
   - 에러 처리:
     - 외부 API 실패 시 `HTTP 502` + `"price search failed: ..."`
   - 인증:
     - `/api/prices`와 동일하게 `X-API-Token` 헤더 기반 토큰 인증 사용

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

1. `/api/prices` 실제 시세 연동
   - Yahoo Finance / 국내 증권 / 암호화폐 거래소(업비트 등) 중 선택
   - `tickers` 리스트 기준으로 현재가 조회 후 `{ ticker: price }` 반환하도록 구현
2. 자산 카테고리별로 시세 소스 분기
   - 예: 한국주식 / 미국주식 / ETF 등
3. CORS 도메인 좁히기
   - 배포된 Vercel 도메인 확정 후 `allow_origins`에 해당 도메인만 추가하는 방식으로 보안 강화
4. 장기적으로:
  - 인증(간단한 토큰) 추가 고려
  - 가격 히스토리 저장(파일/SQLite/Timescale 등) 후, Dashboard의 `historyData`를 백엔드 기반으로 교체
