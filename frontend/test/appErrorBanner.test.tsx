import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Layout } from '../src/app/Layout';
import { APP_ERROR_EVENT } from '@/shared/errors';

import { SettingsProvider } from '../hooks/SettingsContext';
import { QueryProvider } from '../src/app/providers/QueryProvider';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

describe('Layout error banner', () => {
  it('shows an error banner when app error event fires', async () => {
    render(
      <SettingsProvider>
        <QueryProvider>
          <BrowserRouter>
            <Routes>
              <Route path="*" element={<Layout />} />
            </Routes>
          </BrowserRouter>
        </QueryProvider>
      </SettingsProvider>
    );

    await act(async () => { });

    const message = 'Test error';
    act(() => {
      window.dispatchEvent(new CustomEvent(APP_ERROR_EVENT, { detail: message }));
    });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(message);
  });
});
