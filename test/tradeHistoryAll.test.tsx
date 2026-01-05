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

import { TradeHistoryAll } from '../components/TradeHistoryAll';

describe('TradeHistoryAll', () => {
  it('shows an error banner when loading fails', async () => {
    render(
      <TradeHistoryAll
        assets={[]}
        serverUrl="http://localhost"
        apiToken="token"
      />,
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
  });
});
