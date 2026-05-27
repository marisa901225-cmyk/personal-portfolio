import { act, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../hooks/SettingsContext';
import { Layout } from '../src/app/Layout';
import { QueryProvider } from '../src/app/providers/QueryProvider';
import { TradeHistoryAll } from '../components/TradeHistoryAll';
import { APP_ERROR_EVENT } from '@/shared/errors';

vi.mock('@/shared/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api/client')>('@/shared/api/client');
  return {
    ...actual,
    ApiClient: class {
      fetchTrades = vi.fn(() => Promise.reject(new Error('fail')));
    },
  };
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe('error surfaces', () => {
  it('shows an app-level error banner when app error event fires', async () => {
    render(
      <SettingsProvider>
        <QueryProvider>
          <BrowserRouter>
            <Routes>
              <Route path="*" element={<Layout />} />
            </Routes>
          </BrowserRouter>
        </QueryProvider>
      </SettingsProvider>,
    );

    await act(async () => {});

    const message = 'Test error';
    act(() => {
      window.dispatchEvent(new CustomEvent(APP_ERROR_EVENT, { detail: message }));
    });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(message);
  });

  it('shows an error banner when trade history loading fails', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <TradeHistoryAll assets={[]} serverUrl="http://localhost" apiToken="token" />
      </QueryClientProvider>,
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
  });
});
