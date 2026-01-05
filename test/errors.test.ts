import { describe, expect, it } from 'vitest';
import { ApiError, NetworkError } from '../lib/api';
import { getUserErrorMessage } from '../lib/utils/errors';

describe('getUserErrorMessage', () => {
  const messages = {
    default: 'DEFAULT',
    unauthorized: 'UNAUTHORIZED',
    rateLimited: 'RATE',
    network: 'NETWORK',
  };

  it('maps ApiError status codes', () => {
    expect(getUserErrorMessage(new ApiError(401, 'Unauthorized', 'x'), messages)).toBe('UNAUTHORIZED');
    expect(getUserErrorMessage(new ApiError(429, 'Too Many', 'x'), messages)).toBe('RATE');
    expect(getUserErrorMessage(new ApiError(500, 'Oops', 'x'), messages)).toBe('DEFAULT');
  });

  it('maps network errors', () => {
    expect(getUserErrorMessage(new NetworkError('x'), messages)).toBe('NETWORK');
    expect(getUserErrorMessage(new TypeError('fetch failed'), messages)).toBe('NETWORK');
  });
});

