export enum AssetCategory {
  CASH = '현금/예금',
  STOCK_KR = '국내주식',
  STOCK_US = '해외주식',
  CRYPTO = '가상화폐',
  REAL_ESTATE = '부동산',
  OTHER = '기타'
}

export interface Asset {
  id: string;
  name: string;
  ticker?: string; // Yahoo Finance Ticker (e.g., 005930.KS, AAPL)
  category: AssetCategory;
  amount: number; // Quantity
  currentPrice: number; // Price per unit
  currency: 'KRW' | 'USD';
  purchasePrice?: number; // Optional for profit calc
}

export interface PortfolioSummary {
  totalValue: number;
  totalInvested: number;
  categoryDistribution: { name: string; value: number; color: string }[];
  historyData: { date: string; value: number }[];
}

export type ViewState = 'DASHBOARD' | 'LIST' | 'ADD' | 'SETTINGS';

export interface AppSettings {
  serverUrl: string; // Tailscale URL e.g., http://100.x.y.z:8000
}