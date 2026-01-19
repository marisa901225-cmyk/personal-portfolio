/* eslint-disable no-undef */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, type BackendHealthResponse, type BackendPortfolioResponse } from '@/shared/api/client';

describe('ApiClient', () => {
  const baseUrl = 'http://localhost:8000';
  const token = 'test-token';
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('checkHealth calls /api/health with token', async () => {
    const client = new ApiClient(baseUrl, token);
    const mockResponse: BackendHealthResponse = { status: 'ok' };
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockResponse,
    } as Response);

    const result = await client.checkHealth();

    expect(result).toEqual(mockResponse);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${baseUrl}/api/health`);
    expect(options).toMatchObject({ method: 'GET' });
    expect((options as RequestInit).headers).toMatchObject({ 'X-API-Token': token });
  });

  it('fetchPortfolio calls /api/portfolio', async () => {
    const client = new ApiClient(baseUrl, token);
    const mockData: BackendPortfolioResponse = {
      assets: [],
      trades: [],
      summary: {
        total_value: 1000,
        total_invested: 900,
        realized_profit_total: 0,
        unrealized_profit_total: 100,
        category_distribution: [],
        index_distribution: [],
      },
    };
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockData,
    } as Response);

    const result = await client.fetchPortfolio();

    expect(result).toEqual(mockData);
    expect(fetchMock).toHaveBeenCalledWith(`${baseUrl}/api/portfolio`, expect.anything());
  });

  it('fetchExpenses builds query params', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [],
    } as Response);

    await client.fetchExpenses({ year: 2025, month: 1, category: 'Food', includeDeleted: true });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/expenses/?');
    expect(url).toContain('year=2025');
    expect(url).toContain('month=1');
    expect(url).toContain('category=Food');
    expect(url).toContain('include_deleted=true');
  });

  it('deleteExpense uses DELETE', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      text: async () => '',
    } as Response);

    await client.deleteExpense(123);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${baseUrl}/api/expenses/123`);
    expect(options).toMatchObject({ method: 'DELETE' });
  });

  it('throws ApiError when response is not ok', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => 'boom',
    } as Response);

    await expect(client.checkHealth()).rejects.toBeInstanceOf(ApiError);
  });
});
