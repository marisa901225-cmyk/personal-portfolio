export enum AssetCategory {
  CASH = '현금/예금',
  STOCK_KR = '국내주식',
  STOCK_US = '해외주식',
  REAL_ESTATE = '부동산',
  OTHER = '기타'
}

export interface Asset {
  id: string;
  name: string;
  ticker?: string; // Yahoo Finance Ticker (e.g., 005930.KS, AAPL)
  category: AssetCategory;
  amount: number; // Quantity (current holding)
  currentPrice: number; // Price per unit
  currency: 'KRW' | 'USD';
  purchasePrice?: number; // Optional for profit calc
  realizedProfit?: number; // Realized P&L
  /** 어떤 지수/테마에 속하는지 (예: S&P500, NASDAQ100, KOSPI200) */
  indexGroup?: string;
}

export type TradeType = 'BUY' | 'SELL';

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

export interface TargetIndexAllocation {
  indexGroup: string;
  /** 상대 비중 (예: 6, 3, 1) */
  targetWeight: number;
}

export interface PortfolioSummary {
  totalValue: number;
  totalInvested: number;
  realizedProfitTotal: number;
  unrealizedProfitTotal: number;
  categoryDistribution: { name: string; value: number; color: string }[];
  indexDistribution: { name: string; value: number; color: string }[];
  historyData: { date: string; value: number }[];
}

export type ViewState = 'DASHBOARD' | 'LIST' | 'ADD' | 'SETTINGS';

export interface AppSettings {
  serverUrl: string; // Tailscale URL e.g., http://100.x.y.z:8000
  apiToken?: string;
  targetIndexAllocations?: TargetIndexAllocation[];
}
