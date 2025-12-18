import { describe, expect, it } from 'vitest';
import { formatCompactNumber, formatCurrency } from '../constants';

describe('constants formatters', () => {
  it('formatCurrency formats KRW without decimals', () => {
    const formatted = formatCurrency(1234);
    expect(formatted).toMatch(/₩\s?1,234/);
    expect(formatted).not.toMatch(/\.\d/);
  });

  it('formatCompactNumber uses Korean compact units', () => {
    expect(formatCompactNumber(10_000)).toContain('만');
  });
});
