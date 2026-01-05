import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from '../App';
import { APP_ERROR_EVENT } from '../lib/utils/errors';

describe('App error banner', () => {
  it('shows an error banner when app error event fires', async () => {
    render(<App />);

    await act(async () => {});

    const message = 'Test error';
    act(() => {
      window.dispatchEvent(new CustomEvent(APP_ERROR_EVENT, { detail: message }));
    });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(message);
  });
});
