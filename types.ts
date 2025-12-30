export enum AssetCategory {
  CASH = '현금/예금',
  STOCK_KR = '국내주식',
  STOCK_US = '해외주식',
  REAL_ESTATE = '부동산',
  OTHER = '기타'
}

import type { CmaConfig } from './cmaConfig';

export interface Asset {
  id: string;
  /** 백엔드 SQLite 자산 ID (서버 연동용, 선택) */
  backendId?: number;
  name: string;
  ticker?: string; // 시세 조회용 티커 (예: 005930, NAS:AAPL)
  category: AssetCategory;
  amount: number; // Quantity (current holding)
  currentPrice: number; // Price per unit
  currency: 'KRW' | 'USD';
  purchasePrice?: number; // Optional for profit calc
  realizedProfit?: number; // Realized P&L
  /** 어떤 지수/테마에 속하는지 (예: S&P500, NASDAQ100, KOSPI200) */
  indexGroup?: string;
  /** 발행어음/CMA 세후 이자 자동 계산 설정 (선택) */
  cmaConfig?: CmaConfig;
}

export type TradeType = 'BUY' | 'SELL';

export type FxTransactionType = 'BUY' | 'SELL' | 'SETTLEMENT';

export interface TradeRecord {
  id: string;
  assetId: string;
  assetName: string;
  ticker?: string;
  type: TradeType;
  quantity: number;
  price: number;
  timestamp: string;
  realizedDelta?: number;
}

export interface FxTransactionRecord {
  id: string;
  tradeDate: string;
  type: FxTransactionType;
  currency: 'KRW' | 'USD';
  fxAmount?: number;
  krwAmount?: number;
  rate?: number;
  description?: string;
  note?: string;
}

export interface TargetIndexAllocation {
  indexGroup: string;
  /** 목표 비중 값 (예: 6, 3, 1 또는 60, 30, 10 — 합계가 100이면 %로 해석) */
  targetWeight: number;
}

export interface PortfolioSummary {
  totalValue: number;
  totalInvested: number;
  realizedProfitTotal: number;
  unrealizedProfitTotal: number;
  categoryDistribution: { name: string; value: number; color: string }[];
  indexDistribution: { name: string; value: number; color: string }[];
  xirr_rate?: number; // 연평균 수익률
  historyData: { date: string; value: number; stockValue?: number; realEstateValue?: number }[];
}

export type ViewState = 'DASHBOARD' | 'LIST' | 'TRADES' | 'EXCHANGE' | 'ADD' | 'SETTINGS';

export interface DividendEntry {
  year: number;
  total: number;
}

export interface AppSettings {
  serverUrl: string; // Tailscale URL e.g., http://100.x.y.z:8000
  apiToken?: string;
  targetIndexAllocations?: TargetIndexAllocation[];
  /** 대략적인 환차익/환차손 계산용 기준 USD/KRW 환율 */
  usdFxBase?: number;
  /** 현재 USD/KRW 환율 (직접 입력) */
  usdFxNow?: number;
  /** 올해 받은 배당금 총액 (세후, 수동 입력) */
  dividendTotalYear?: number;
  /** 배당금 합계가 어느 연도 기준인지 (예: 2025) */
  dividendYear?: number;
  /** 연도별 배당 합계 리스트 (서버/로컬에 함께 저장) */
  dividends?: DividendEntry[];
  /** 시장지수/벤치마크 이름 (예: SPY TR) */
  benchmarkName?: string;
  /** 시장지수 수익률 (%) */
  benchmarkReturn?: number;
  // 외관 설정
  /** 배경 이미지 사용 여부 */
  bgEnabled?: boolean;
  /** 배경 이미지 데이터 (로컬스토리지에 Base64로 저장) */
  bgImageData?: string;
  /** 카드 불투명도 (0~100, 기본 85) */
  cardOpacity?: number;
  /** 배경 흐림 강도 (0~20, 기본 8) */
  bgBlur?: number;
}
