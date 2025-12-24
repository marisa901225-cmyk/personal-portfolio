# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
> 
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
> 
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
> 
> ---
> 
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Persist settings locally and merge with server values | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Add API request timeouts and classify timeouts | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Export trade history to CSV | P3 | ⬜ Pending |

| **Total: 3 prompts** | **Completed: 0** | **Remaining: 3**
---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Persist settings locally and merge with server values

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Persist non-sensitive settings to localStorage, hydrate on load, and keep server-synced values merged without storing `apiToken`.  
**Files to Modify**: `hooks/useSettings.ts`

#### Instructions:

1. Open `hooks/useSettings.ts`.
2. Add localStorage helpers that load/save only non-sensitive fields (exclude `apiToken`).
3. Initialize state from localStorage merged with `DEFAULT_SETTINGS`.
4. Persist changes to localStorage via `useEffect`.

#### Implementation Code:

```typescript
import { useEffect, useState } from 'react';
import { AppSettings, DividendEntry, TargetIndexAllocation } from '../types';
import { alertError } from '../errors';
import { ApiClient, BackendSettings } from '../backendClient';

const DEFAULT_SETTINGS: AppSettings = {
  serverUrl: 'https://dlckdgn-nucboxg3-plus.tail5c2348.ts.net',
  targetIndexAllocations: [
    { indexGroup: 'S&P500', targetWeight: 6 },
    { indexGroup: 'NASDAQ100', targetWeight: 3 },
    { indexGroup: 'BOND+ETC', targetWeight: 1 },
  ],
  usdFxBase: undefined,
  usdFxNow: undefined,
  dividendTotalYear: undefined,
  dividendYear: undefined,
  dividends: [],
  bgEnabled: false,
  bgImageData: undefined,
  cardOpacity: 85,
  bgBlur: 8,
};

const LOCAL_SETTINGS_KEY = 'portfolio.settings';

const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const normalizeTargetIndexAllocations = (
  value: unknown,
): TargetIndexAllocation[] | undefined => {
  if (!Array.isArray(value)) return undefined;

  const normalized = value
    .map((raw) => {
      if (!raw || typeof raw !== 'object') return null;
      const indexGroup =
        typeof (raw as { indexGroup?: unknown }).indexGroup === 'string'
          ? (raw as { indexGroup: string }).indexGroup.trim()
          : '';
      const targetWeight = (raw as { targetWeight?: unknown }).targetWeight;
      if (!indexGroup || !isNumber(targetWeight)) return null;
      return { indexGroup, targetWeight };
    })
    .filter(Boolean) as TargetIndexAllocation[];

  return normalized.length > 0 ? normalized : undefined;
};

const normalizeDividends = (value: unknown): DividendEntry[] | undefined => {
  if (!Array.isArray(value)) return undefined;

  const normalized = value
    .map((raw) => {
      if (!raw || typeof raw !== 'object') return null;
      const year = (raw as { year?: unknown }).year;
      const total = (raw as { total?: unknown }).total;
      if (!isNumber(year) || !isNumber(total)) return null;
      return { year, total };
    })
    .filter(Boolean) as DividendEntry[];

  return normalized.length > 0 ? normalized : undefined;
};

const loadLocalSettings = (): Partial<AppSettings> => {
  if (typeof window === 'undefined') return {};
  const raw = window.localStorage.getItem(LOCAL_SETTINGS_KEY);
  if (!raw) return {};

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const data = parsed as Record<string, unknown>;
    const result: Partial<AppSettings> = {};

    if (typeof data.serverUrl === 'string') result.serverUrl = data.serverUrl;

    const allocations = normalizeTargetIndexAllocations(data.targetIndexAllocations);
    if (allocations) result.targetIndexAllocations = allocations;

    if (isNumber(data.usdFxBase)) result.usdFxBase = data.usdFxBase;
    if (isNumber(data.usdFxNow)) result.usdFxNow = data.usdFxNow;

    if (isNumber(data.dividendTotalYear)) result.dividendTotalYear = data.dividendTotalYear;
    if (isNumber(data.dividendYear)) result.dividendYear = data.dividendYear;

    const dividends = normalizeDividends(data.dividends);
    if (dividends) result.dividends = dividends;

    if (typeof data.bgEnabled === 'boolean') result.bgEnabled = data.bgEnabled;
    if (typeof data.bgImageData === 'string') result.bgImageData = data.bgImageData;
    if (isNumber(data.cardOpacity)) result.cardOpacity = data.cardOpacity;
    if (isNumber(data.bgBlur)) result.bgBlur = data.bgBlur;

    return result;
  } catch {
    return {};
  }
};

const pickPersistedSettings = (settings: AppSettings): Partial<AppSettings> => ({
  serverUrl: settings.serverUrl,
  targetIndexAllocations: settings.targetIndexAllocations,
  usdFxBase: settings.usdFxBase,
  usdFxNow: settings.usdFxNow,
  dividendTotalYear: settings.dividendTotalYear,
  dividendYear: settings.dividendYear,
  dividends: settings.dividends,
  bgEnabled: settings.bgEnabled,
  bgImageData: settings.bgImageData,
  cardOpacity: settings.cardOpacity,
  bgBlur: settings.bgBlur,
});

export const useSettings = () => {
  const [settings, setSettings] = useState<AppSettings>(() => ({
    ...DEFAULT_SETTINGS,
    ...loadLocalSettings(),
  }));

  const saveSettingsToServer = async (current: AppSettings): Promise<void> => {
    if (!current.serverUrl || !current.apiToken) {
      return;
    }

    const payload = {
      target_index_allocations: (current.targetIndexAllocations || [])
        .filter((a) => a.indexGroup && a.targetWeight >= 0)
        .map((a) => ({
          index_group: a.indexGroup,
          target_weight: a.targetWeight,
        })),
      server_url: current.serverUrl,
      dividend_year: current.dividendYear ?? null,
      dividend_total: current.dividendTotalYear ?? null,
      dividends: (current.dividends || []).map((d) => ({
        year: d.year,
        total: d.total,
      })),
      usd_fx_base: current.usdFxBase ?? null,
      usd_fx_now: current.usdFxNow ?? null,
    };

    try {
      const apiClient = new ApiClient(current.serverUrl, current.apiToken);
      const data: BackendSettings = await apiClient.updateSettings(payload);
      if (Array.isArray(data.target_index_allocations)) {
        const mapped = data.target_index_allocations.map((item) => ({
          indexGroup: item.index_group,
          targetWeight: item.target_weight,
        }));
        setSettings((prev) => ({
          ...prev,
          targetIndexAllocations: mapped,
        }));
      }

      if (typeof data.dividend_year === 'number' || typeof data.dividend_total === 'number') {
        setSettings((prev) => ({
          ...prev,
          dividendYear: data.dividend_year ?? prev.dividendYear,
          dividendTotalYear: data.dividend_total ?? prev.dividendTotalYear,
        }));
      }

      if (Array.isArray(data.dividends)) {
        const mappedDividends: DividendEntry[] = data.dividends.map((d) => ({
          year: d.year,
          total: d.total,
        }));
        setSettings((prev) => ({
          ...prev,
          dividends: mappedDividends,
        }));
      }

      if (data.usd_fx_base !== undefined || data.usd_fx_now !== undefined) {
        setSettings((prev) => ({
          ...prev,
          usdFxBase: data.usd_fx_base ?? undefined,
          usdFxNow: data.usd_fx_now ?? undefined,
        }));
      }
    } catch (error) {
      alertError('Save settings error', error, {
        default: '서버와 통신 중 오류가 발생했습니다.\n설정이 서버에 저장되지 않았을 수 있습니다.',
        unauthorized: '설정을 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
        network: '서버와 통신할 수 없습니다.\n설정이 서버에 저장되지 않았을 수 있습니다.',
      });
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const payload = pickPersistedSettings(settings);
    window.localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(payload));
  }, [settings]);

  useEffect(() => {
    if (!settings.serverUrl || !settings.apiToken) {
      return;
    }

    const load = async () => {
      try {
        const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);
        const data: BackendSettings = await apiClient.fetchSettings();
        if (Array.isArray(data.target_index_allocations)) {
          const mapped = data.target_index_allocations.map((item) => ({
            indexGroup: item.index_group,
            targetWeight: item.target_weight,
          }));
          setSettings((prev) => ({
            ...prev,
            targetIndexAllocations: mapped,
          }));
        }

        if (typeof data.dividend_year === 'number' || typeof data.dividend_total === 'number') {
          setSettings((prev) => ({
            ...prev,
            dividendYear: data.dividend_year ?? prev.dividendYear,
            dividendTotalYear: data.dividend_total ?? prev.dividendTotalYear,
          }));
        }

        if (Array.isArray(data.dividends)) {
          const mappedDividends: DividendEntry[] = data.dividends.map((d) => ({
            year: d.year,
            total: d.total,
          }));
          setSettings((prev) => ({
            ...prev,
            dividends: mappedDividends,
          }));
        }

        if (data.usd_fx_base !== undefined || data.usd_fx_now !== undefined) {
          setSettings((prev) => ({
            ...prev,
            usdFxBase: data.usd_fx_base ?? undefined,
            usdFxNow: data.usd_fx_now ?? undefined,
          }));
        }
      } catch (error) {
        alertError('Failed to load settings from server', error, {
          default: '설정을 불러오지 못했습니다.\n서버 상태를 확인해주세요.',
          unauthorized: '설정을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '설정을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        });
      }
    };

    void load();
  }, [settings.serverUrl, settings.apiToken]);

  useEffect(() => {
    if (!settings.serverUrl || !settings.apiToken) {
      return;
    }

    let isActive = true;
    const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);

    const fetchFxNow = async () => {
      try {
        const data = await apiClient.fetchUsdKrwFxRate();
        const rateNum = data?.rate;
        if (!rateNum || !Number.isFinite(rateNum)) {
          return;
        }
        if (isActive) {
          setSettings((prev) => ({
            ...prev,
            usdFxNow: rateNum,
          }));
        }
      } catch {
        // 자동 갱신 실패는 조용히 무시
      }
    };

    void fetchFxNow();
    const interval = window.setInterval(fetchFxNow, 10 * 60 * 1000);
    return () => {
      isActive = false;
      window.clearInterval(interval);
    };
  }, [settings.serverUrl, settings.apiToken]);

  return { settings, setSettings, saveSettingsToServer };
};
```

#### Verification:
- Run: `npm run typecheck`
- Expected: No TypeScript errors

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] Add API request timeouts and classify timeouts

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add request timeouts to ApiClient using AbortController and classify timeout errors so the UI can display better messages.  
**Files to Modify**: `backendClient.ts`, `errors.ts`

#### Instructions:

1. Open `backendClient.ts` and add `TimeoutError`, a default timeout, and AbortController logic inside `request`.
2. Update `errors.ts` to recognize `TimeoutError` and allow a `timeout` message.

#### Implementation Code:

File: `backendClient.ts`
```typescript
import { Asset, TradeRecord, TradeType, FxTransactionRecord, FxTransactionType } from './types';

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

export class TimeoutError extends Error {
  constructor(public readonly url: string, public readonly timeoutMs: number) {
    super(
      `API Request Timed Out: ${url}${timeoutMs > 0 ? ` (${timeoutMs}ms)` : ''}`,
    );
    this.name = 'TimeoutError';
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
  usd_fx_base?: number | null;
  usd_fx_now?: number | null;
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

export interface BackendFxTransaction {
  id: number;
  user_id: number;
  trade_date: string;
  type: 'BUY' | 'SELL' | 'SETTLEMENT';
  currency: 'KRW' | 'USD';
  fx_amount?: number | null;
  krw_amount?: number | null;
  rate?: number | null;
  description?: string | null;
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

export const mapBackendFxToFrontend = (
  backend: BackendFxTransaction,
): FxTransactionRecord => ({
  id: backend.id.toString(),
  tradeDate: backend.trade_date,
  type: backend.type,
  currency: backend.currency,
  fxAmount: backend.fx_amount ?? undefined,
  krwAmount: backend.krw_amount ?? undefined,
  rate: backend.rate ?? undefined,
  description: backend.description ?? undefined,
  note: backend.note ?? undefined,
});

const DEFAULT_TIMEOUT_MS = 15000;

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  'name' in error &&
  (error as { name?: string }).name === 'AbortError';

// --- API Client ---

export class ApiClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(baseUrl: string, private apiToken?: string, timeoutMs = DEFAULT_TIMEOUT_MS) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.timeoutMs = timeoutMs;
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
    timeoutMs?: number,
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      ...this.createHeaders(
        options.method !== 'GET' && options.method !== 'DELETE',
      ),
      ...(options.headers || {}),
    };

    const controller = new AbortController();
    if (options.signal) {
      if (options.signal.aborted) {
        controller.abort();
      } else {
        options.signal.addEventListener('abort', () => controller.abort(), { once: true });
      }
    }

    const timeout = typeof timeoutMs === 'number' ? timeoutMs : this.timeoutMs;
    const shouldTimeout = Number.isFinite(timeout) && timeout > 0;
    const timeoutId = shouldTimeout
      ? globalThis.setTimeout(() => controller.abort(), timeout)
      : undefined;

    let response: Response;
    try {
      response = await fetch(url, { ...options, headers, signal: controller.signal });
    } catch (error) {
      if (isAbortError(error)) {
        throw new TimeoutError(url, shouldTimeout ? timeout : 0);
      }
      throw new NetworkError(url, error);
    } finally {
      if (timeoutId) {
        globalThis.clearTimeout(timeoutId);
      }
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

  // --- FX Transactions ---

  async fetchFxTransactions(params?: {
    limit?: number;
    beforeId?: number;
    kind?: FxTransactionType;
    startDate?: string;
    endDate?: string;
  }): Promise<BackendFxTransaction[]> {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set('limit', params.limit.toString());
    if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
    if (params?.kind != null) search.set('kind', params.kind);
    if (params?.startDate) search.set('start_date', params.startDate);
    if (params?.endDate) search.set('end_date', params.endDate);
    const qs = search.toString();
    return this.request<BackendFxTransaction[]>(`/api/exchanges${qs ? `?${qs}` : ''}`, {
      method: 'GET',
    });
  }

  async createFxTransaction(payload: {
    trade_date: string;
    type: FxTransactionType;
    currency: 'KRW' | 'USD';
    fx_amount?: number | null;
    krw_amount?: number | null;
    rate?: number | null;
    description?: string | null;
    note?: string | null;
  }): Promise<BackendFxTransaction> {
    return this.request<BackendFxTransaction>('/api/exchanges', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateFxTransaction(
    recordId: number,
    payload: {
      trade_date?: string;
      type?: FxTransactionType;
      currency?: 'KRW' | 'USD';
      fx_amount?: number | null;
      krw_amount?: number | null;
      rate?: number | null;
      description?: string | null;
      note?: string | null;
    },
  ): Promise<BackendFxTransaction> {
    return this.request<BackendFxTransaction>(`/api/exchanges/${recordId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async deleteFxTransaction(recordId: number): Promise<void> {
    return this.request<void>(`/api/exchanges/${recordId}`, {
      method: 'DELETE',
    });
  }
}
```

File: `errors.ts`
```typescript
import { ApiError, NetworkError, TimeoutError } from './backendClient';

export type UserErrorMessages = {
  default: string;
  unauthorized?: string;
  rateLimited?: string;
  network?: string;
  timeout?: string;
};

export const isNetworkError = (error: unknown): boolean => {
  if (error instanceof NetworkError) return true;
  if (error instanceof TimeoutError) return true;
  if (error instanceof TypeError) return true;
  return false;
};

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

export const isApiErrorStatus = (error: unknown, status: number): boolean =>
  error instanceof ApiError && error.status === status;

export const getUserErrorMessage = (error: unknown, messages: UserErrorMessages): string => {
  if (error instanceof TimeoutError) {
    return messages.timeout ?? messages.network ?? messages.default;
  }

  if (isApiError(error)) {
    if (isApiErrorStatus(error, 401) && messages.unauthorized) return messages.unauthorized;
    if (isApiErrorStatus(error, 429) && messages.rateLimited) return messages.rateLimited;
    return messages.default;
  }

  if (isNetworkError(error)) {
    return messages.network ?? messages.default;
  }

  return messages.default;
};

export const alertError = (context: string, error: unknown, messages: UserErrorMessages): void => {
  console.error(context, error);
  if (typeof window !== 'undefined') {
    window.alert(getUserErrorMessage(error, messages));
  }
};
```

#### Verification:
- Run: `npm run typecheck`
- Expected: No TypeScript errors

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

 (removed)
```

File: `App.tsx` (update hook destructuring and Dashboard props)
```typescript
  const {
    assets,
    tradeHistory,
    historyData,
    summaryFromServer,
    isSyncing,
    addAsset,
    deleteAsset,
    tradeAsset,
    syncPrices,
    updateAsset,
    updateCashBalance,
    restoreFromBackup,
    createSnapshot,
  } = usePortfolio(settings);
```

```typescript
        {currentView === 'DASHBOARD' && (
          <Dashboard
            assets={assets}
            backendSummary={summaryFromServer}
            usdFxBase={settings.usdFxBase}
            usdFxNow={settings.usdFxNow}
            targetIndexAllocations={settings.targetIndexAllocations}
            historyData={historyData}
            dividendTotalYear={settings.dividendTotalYear}
            dividendYear={settings.dividendYear}
            dividends={settings.dividends}
            onUpdateDividends={() => setIsDividendModalOpen(true)}
            onCreateSnapshot={createSnapshot}
          />
        )}
```

#### Verification:
- Run: `npm run typecheck`
- Expected: No TypeScript errors

**✅ After completing this prompt, proceed to [PROMPT-004]**

---

### [PROMPT-004] Export trade history to CSV

**⏱️ Execute this prompt now, then proceed to PROMPT-004**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add a CSV export button for the filtered trade history list.  
**Files to Modify**: `components/TradeHistoryAll.tsx`

#### Instructions:

1. Add a CSV export handler that uses the current filtered list.
2. Add a "CSV 다운로드" button near the existing refresh controls.

#### Implementation Code:

```typescript
import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, RefreshCw, Search, Download } from 'lucide-react';
import { ApiClient, BackendTrade, mapBackendTradesToFrontend } from '../backendClient';
import { formatCurrency } from '../constants';
import { getUserErrorMessage } from '../errors';
import type { Asset, TradeRecord, TradeType } from '../types';

type TradeFilter = 'ALL' | TradeType;

type TradeHistoryVariant = 'page' | 'collapsible';

interface TradeHistoryAllProps {
  assets: Asset[];
  serverUrl: string;
  apiToken?: string;
  variant?: TradeHistoryVariant;
}

const PAGE_SIZE = 100;

export const TradeHistoryAll: React.FC<TradeHistoryAllProps> = ({
  assets,
  serverUrl,
  apiToken,
  variant = 'page',
}) => {
  const isCollapsible = variant === 'collapsible';
  const [isOpen, setIsOpen] = useState(!isCollapsible);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [cursorBeforeId, setCursorBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [tradeFilter, setTradeFilter] = useState<TradeFilter>('ALL');

  const isRemoteEnabled = Boolean(serverUrl && apiToken);

  const apiClient = useMemo(() => {
    return new ApiClient(serverUrl, apiToken);
  }, [serverUrl, apiToken]);

  const loadTrades = async ({ reset }: { reset: boolean }) => {
    if (!isRemoteEnabled) return;
    if (isLoading) return;
    if (!hasMore && !reset) return;

    const beforeId = reset ? undefined : cursorBeforeId ?? undefined;

    setIsLoading(true);
    setLoadError(null);

    try {
      const backendTrades = await apiClient.fetchTrades({ limit: PAGE_SIZE, beforeId });
      if (backendTrades.length === 0) {
        setHasMore(false);
        return;
      }

      const mapped = mapBackendTradesToFrontend(backendTrades, assets);
      setTrades((prev) => (reset ? mapped : [...prev, ...mapped]));

      const last: BackendTrade = backendTrades[backendTrades.length - 1];
      setCursorBeforeId(last.id);
      setHasMore(backendTrades.length === PAGE_SIZE);
    } catch (error) {
      setLoadError(
        getUserErrorMessage(error, {
          default: '거래 내역을 불러오지 못했습니다.',
          unauthorized: '거래 내역을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '거래 내역을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
          timeout: '요청 시간이 초과되었습니다.\n잠시 후 다시 시도해주세요.',
        }),
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async () => {
    setTrades([]);
    setCursorBeforeId(null);
    setHasMore(true);
    await loadTrades({ reset: true });
  };

  useEffect(() => {
    setTrades([]);
    setCursorBeforeId(null);
    setHasMore(true);
    setLoadError(null);
    setIsLoading(false);
  }, [serverUrl, apiToken]);

  useEffect(() => {
    if (isCollapsible && !isOpen) return;
    if (!isRemoteEnabled) return;
    if (trades.length > 0) return;
    void loadTrades({ reset: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, isRemoteEnabled, isCollapsible]);

  const filteredTrades = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return trades.filter((trade) => {
      if (tradeFilter !== 'ALL' && trade.type !== tradeFilter) return false;
      if (!query) return true;
      const name = trade.assetName.toLowerCase();
      const ticker = (trade.ticker || '').toLowerCase();
      return name.includes(query) || ticker.includes(query);
    });
  }, [trades, tradeFilter, searchTerm]);

  const escapeCsvValue = (value: string | number | undefined): string => {
    const text = value == null ? '' : String(value);
    const escaped = text.replace(/"/g, '""');
    return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
  };

  const handleExportCsv = () => {
    if (filteredTrades.length === 0) {
      alert('내보낼 거래 내역이 없습니다.');
      return;
    }

    const rows = [
      ['일시', '구분', '자산', '티커', '수량', '가격', '실현손익'],
      ...filteredTrades.map((trade) => [
        new Date(trade.timestamp).toLocaleString('ko-KR'),
        trade.type === 'BUY' ? '매수' : '매도',
        trade.assetName,
        trade.ticker ?? '',
        trade.quantity,
        trade.price,
        trade.realizedDelta ?? '',
      ]),
    ];

    const csv = rows.map((row) => row.map(escapeCsvValue).join(',')).join('\n');
    const dateStr = new Date().toISOString().slice(0, 10);
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `trade_history_${dateStr}.csv`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const tradeFilters: { key: TradeFilter; label: string }[] = [
    { key: 'ALL', label: '전체' },
    { key: 'BUY', label: '매수' },
    { key: 'SELL', label: '매도' },
  ];

  return (
    <section className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">전체 거래 내역</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {isRemoteEnabled ? '과거 거래까지 페이지로 불러옵니다.' : '서버 연결이 필요합니다. (설정/로그인)'}
          </p>
        </div>
        {isCollapsible && (
          <button
            type="button"
            onClick={() => setIsOpen((prev) => !prev)}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 transition-colors"
          >
            {isOpen ? '닫기' : '열기'}
            {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        )}
      </div>

      {(!isCollapsible || isOpen) && (
        <div className="mt-4">
          {!isRemoteEnabled ? (
            <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
              전체 거래 내역은 백엔드 서버 연결 시에만 조회할 수 있어요.
            </div>
          ) : (
            <>
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                <div className="relative flex-1 max-w-md">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="자산명/티커 검색..."
                    className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1">
                    {tradeFilters.map(({ key, label }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setTradeFilter(key)}
                        className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${tradeFilter === key
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                          }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={handleExportCsv}
                    disabled={filteredTrades.length === 0}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    <Download size={14} />
                    CSV 다운로드
                  </button>

                  <button
                    type="button"
                    onClick={() => void handleRefresh()}
                    disabled={isLoading}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
                    새로고침
                  </button>
                </div>
              </div>

              {loadError && (
                <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">
                  {loadError}
                </div>
              )}

              <div className="mt-3">
                {filteredTrades.length === 0 ? (
                  <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
                    {trades.length === 0 ? '거래 내역이 없습니다.' : '조건에 맞는 거래가 없습니다.'}
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-slate-400 border-b border-slate-100">
                          <th className="py-2 text-left">날짜</th>
                          <th className="py-2 text-left">자산</th>
                          <th className="py-2 text-left">구분</th>
                          <th className="py-2 text-right">수량</th>
                          <th className="py-2 text-right">가격</th>
                          <th className="py-2 text-right">실현손익</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredTrades.map((trade) => (
                          <tr key={trade.id} className="border-b border-slate-100 last:border-b-0">
                            <td className="py-2 text-slate-500 whitespace-nowrap">
                              {new Date(trade.timestamp).toLocaleString('ko-KR')}
                            </td>
                            <td className="py-2">
                              <div className="font-medium text-slate-800">{trade.assetName}</div>
                              {trade.ticker && (
                                <div className="text-[11px] text-slate-400">{trade.ticker}</div>
                              )}
                            </td>
                            <td className="py-2">
                              <span className={`text-xs px-2 py-1 rounded-lg ${trade.type === 'BUY'
                                ? 'bg-emerald-50 text-emerald-600'
                                : 'bg-rose-50 text-rose-600'
                                }`}
                              >
                                {trade.type === 'BUY' ? '매수' : '매도'}
                              </span>
                            </td>
                            <td className="py-2 text-right">{trade.quantity.toLocaleString()}</td>
                            <td className="py-2 text-right">{formatCurrency(trade.price)}</td>
                            <td className="py-2 text-right text-xs text-slate-500">
                              {trade.realizedDelta != null
                                ? `${trade.realizedDelta >= 0 ? '+' : ''}${formatCurrency(trade.realizedDelta)}`
                                : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="mt-4 flex items-center justify-between">
                <div className="text-xs text-slate-400">
                  {filteredTrades.length.toLocaleString()}건 표시됨
                </div>
                {hasMore && (
                  <button
                    type="button"
                    onClick={() => void loadTrades({ reset: false })}
                    disabled={isLoading}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    {isLoading ? '불러오는 중...' : '더 불러오기'}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
};
```

#### Verification:
- Run: `npm run typecheck`
- Expected: No TypeScript errors

**✅ After completing this prompt, proceed to [PROMPT-004]**

**🎉 ALL PROMPTS COMPLETED!**
<!-- GENERATED: 2025-12-24 14:24 -->
