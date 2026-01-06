import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api');
  return {
    ...actual,
    ApiClient: class {
      fetchTrades = vi.fn(() => Promise.reject(new Error('fail')));
    },
  };
});

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TradeHistoryAll } from '../components/TradeHistoryAll';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe('TradeHistoryAll', () => {
  it('shows an error banner when loading fails', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <TradeHistoryAll
          assets={[]}
          serverUrl="http://localhost"
          apiToken="token"
        />
      </QueryClientProvider>,
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
  });
});
