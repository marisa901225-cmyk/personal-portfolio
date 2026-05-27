import { describe, expect, it } from 'vitest';
import { formatCompactNumber, formatCurrency } from '@/shared/portfolio';
import { ApiError, NetworkError, getUserErrorMessage } from '@/shared/errors';

describe('shared utils', () => {
  it('formatCurrency formats KRW without decimals', () => {
    const formatted = formatCurrency(1234);
    expect(formatted).toMatch(/₩\s?1,234/);
    expect(formatted).not.toMatch(/\.\d/);
  });

  it('formatCompactNumber uses Korean compact units', () => {
    expect(formatCompactNumber(10_000)).toContain('만');
  });

  it('maps ApiError status codes to user messages', () => {
    const messages = {
      default: 'DEFAULT',
      unauthorized: 'UNAUTHORIZED',
      rateLimited: 'RATE',
      network: 'NETWORK',
    };

    expect(getUserErrorMessage(new ApiError(401, 'Unauthorized', 'x'), messages)).toBe('UNAUTHORIZED');
    expect(getUserErrorMessage(new ApiError(429, 'Too Many', 'x'), messages)).toBe('RATE');
    expect(getUserErrorMessage(new ApiError(500, 'Oops', 'x'), messages)).toBe('DEFAULT');
    expect(getUserErrorMessage(new NetworkError('x'), messages)).toBe('NETWORK');
    expect(getUserErrorMessage(new TypeError('fetch failed'), messages)).toBe('NETWORK');
  });
});
