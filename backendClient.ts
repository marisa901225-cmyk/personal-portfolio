import { Asset, TradeRecord } from './types';

// --- 백엔드 포트폴리오 API 응답 타입 (프론트 전용 타입) ---

export interface BackendAsset {
  id: number;
  name: string;
  ticker?: string | null;
  category: string;
  currency: 'KRW' | 'USD';
  amount: number;
  current_price: number;
  purchase_price?: number | null;
  realized_profit: number;
  index_group?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackendTrade {
  id: number;
  asset_id: number;
  user_id: number;
  type: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  timestamp: string;
  realized_delta?: number | null;
  note?: string | null;
  created_at: string;
  updated_at: string;
}

interface BackendDistributionItem {
  name: string;
  value: number;
}

export interface BackendPortfolioSummary {
  total_value: number;
  total_invested: number;
  realized_profit_total: number;
  unrealized_profit_total: number;
  category_distribution: BackendDistributionItem[];
  index_distribution: BackendDistributionItem[];
}

export interface BackendPortfolioResponse {
  assets: BackendAsset[];
  trades: BackendTrade[];
  summary: BackendPortfolioSummary;
}

export interface BackendSnapshot {
  id: number;
  snapshot_at: string;
  total_value: number;
  total_invested: number;
  realized_profit_total: number;
  unrealized_profit_total: number;
}

// --- 매핑 헬퍼 ---

export const mapBackendAssetToFrontend = (backend: BackendAsset): Asset => ({
  id: backend.id.toString(),
  backendId: backend.id,
  name: backend.name,
  ticker: backend.ticker ?? undefined,
  category: backend.category as Asset['category'],
  amount: backend.amount,
  currentPrice: backend.current_price,
  currency: backend.currency,
  purchasePrice: backend.purchase_price ?? undefined,
  realizedProfit: backend.realized_profit,
  indexGroup: backend.index_group ?? undefined,
});

export const mapBackendTradesToFrontend = (
  backendTrades: BackendTrade[],
  frontendAssets: Asset[],
): TradeRecord[] => {
  const assetMap = new Map<string, Asset>();
  frontendAssets.forEach((a) => assetMap.set(a.id, a));

  return backendTrades.map((t) => {
    const assetId = t.asset_id.toString();
    const asset = assetMap.get(assetId);
    return {
      id: t.id.toString(),
      assetId,
      assetName: asset?.name ?? '알 수 없는 자산',
      ticker: asset?.ticker,
      type: t.type,
      quantity: t.quantity,
      price: t.price,
      timestamp: t.timestamp,
      realizedDelta: t.realized_delta ?? undefined,
    };
  });
};

