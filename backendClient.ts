import { Asset, TradeRecord, TradeType } from './types';

// --- 백엔드 포트폴리오 API 응답 타입 (프론트 전용 타입) ---

export class NetworkError extends Error {
  constructor(public readonly url: string, cause?: unknown) {
    super(`Network request failed: ${url}`, { cause });
    this.name = 'NetworkError';
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly url: string,
    public readonly bodyText?: string,
  ) {
    super(
      `API Request Failed: ${status} ${statusText}${bodyText ? ` - ${bodyText}` : ''}`,
    );
    this.name = 'ApiError';
  }
}

export interface BackendCmaConfig {
  principal: number;
  annual_rate: number;
  tax_rate: number;
  start_date: string;
}

export interface BackendTargetIndexAllocation {
  index_group: string;
  target_weight: number;
}

export interface BackendDividend {
  year: number;
  total: number;
}

export interface BackendSettings {
  target_index_allocations?: BackendTargetIndexAllocation[];
  server_url?: string | null;
  dividend_year?: number | null;
  dividend_total?: number | null;
  dividends?: BackendDividend[] | null;
}

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
  cma_config?: BackendCmaConfig | null;
  created_at: string;
  updated_at: string;
}

export interface BackendTrade {
  id: number;
  asset_id: number;
  asset_name?: string | null;
  asset_ticker?: string | null;
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

export interface BackendHealthResponse {
  status: string;
}

export interface BackendFxRateResponse {
  base: string;
  quote: string;
  rate: number;
}

export interface BackendTickerInfo {
  symbol: string;
  name: string;
  exchange?: string | null;
  currency?: string | null;
  type?: string | null;
}

export interface BackendTickerSearchResponse {
  query: string;
  results: BackendTickerInfo[];
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
  cmaConfig: backend.cma_config
    ? {
      principal: backend.cma_config.principal,
      annualRate: backend.cma_config.annual_rate,
      taxRate: backend.cma_config.tax_rate,
      startDate: backend.cma_config.start_date,
    }
    : undefined,
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
      assetName: t.asset_name ?? asset?.name ?? '알 수 없는 자산',
      ticker: t.asset_ticker ?? asset?.ticker,
      type: t.type,
      quantity: t.quantity,
      price: t.price,
      timestamp: t.timestamp,
      realizedDelta: t.realized_delta ?? undefined,
    };
  });
};

// --- API Client ---

export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string, private apiToken?: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private createHeaders(withJson = false): HeadersInit {
    const headers: HeadersInit = withJson
      ? { 'Content-Type': 'application/json' }
      : {};
    if (this.apiToken) {
      headers['X-API-Token'] = this.apiToken;
    }
    return headers;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      ...this.createHeaders(
        options.method !== 'GET' && options.method !== 'DELETE',
      ),
      ...(options.headers || {}),
    };

    let response: Response;
    try {
      response = await fetch(url, { ...options, headers });
    } catch (error) {
      throw new NetworkError(url, error);
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new ApiError(response.status, response.statusText, url, errorText);
    }

    // DELETE 등 응답이 없는 경우가 있을 수 있음
    if (response.status === 204) {
      return {} as T;
    }

    try {
      return await response.json();
    } catch {
      return {} as T;
    }
  }

  // --- Portfolio ---

  async fetchPortfolio(): Promise<BackendPortfolioResponse> {
    return this.request<BackendPortfolioResponse>('/api/portfolio', {
      method: 'GET',
    });
  }

  async fetchSnapshots(days = 180): Promise<BackendSnapshot[]> {
    return this.request<BackendSnapshot[]>(
      `/api/portfolio/snapshots?days=${days}`,
      { method: 'GET' },
    );
  }

  // --- Health ---

  async checkHealth(): Promise<BackendHealthResponse> {
    return this.request<BackendHealthResponse>('/health', { method: 'GET' });
  }

  // --- Settings ---

  async fetchSettings(): Promise<BackendSettings> {
    return this.request<BackendSettings>('/api/settings', { method: 'GET' });
  }

  async updateSettings(payload: BackendSettings): Promise<BackendSettings> {
    return this.request<BackendSettings>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  // --- Assets ---

  async createAsset(payload: any): Promise<BackendAsset> {
    return this.request<BackendAsset>('/api/assets', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async deleteAsset(assetId: number): Promise<void> {
    return this.request<void>(`/api/assets/${assetId}`, {
      method: 'DELETE',
    });
  }

  async updateAsset(assetId: number, payload: any): Promise<BackendAsset> {
    return this.request<BackendAsset>(`/api/assets/${assetId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async fetchPrices(tickers: string[]): Promise<Record<string, number>> {
    return this.request<Record<string, number>>('/api/kis/prices', {
      method: 'POST',
      body: JSON.stringify({ tickers }),
    });
  }

  async fetchUsdKrwFxRate(): Promise<BackendFxRateResponse> {
    return this.request<BackendFxRateResponse>('/api/kis/fx/usdkrw', { method: 'GET' });
  }

  async searchTicker(query: string): Promise<BackendTickerSearchResponse> {
    const q = query.trim();
    return this.request<BackendTickerSearchResponse>(
      `/api/search_ticker?q=${encodeURIComponent(q)}`,
      { method: 'GET' },
    );
  }

  // --- Trades ---

  async fetchTrades(params?: {
    limit?: number;
    beforeId?: number;
    assetId?: number;
  }): Promise<BackendTrade[]> {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set('limit', params.limit.toString());
    if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
    if (params?.assetId != null) search.set('asset_id', params.assetId.toString());
    const qs = search.toString();
    return this.request<BackendTrade[]>(`/api/trades${qs ? `?${qs}` : ''}`, { method: 'GET' });
  }

  async createTrade(
    assetId: number,
    type: TradeType,
    quantity: number,
    price: number,
  ): Promise<BackendTrade> {
    return this.request<BackendTrade>(`/api/assets/${assetId}/trades`, {
      method: 'POST',
      body: JSON.stringify({ type, quantity, price }),
    });
  }
}
