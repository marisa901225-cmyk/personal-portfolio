import { describe, expect, it } from 'vitest';
import { AssetCategory } from '../lib/types';
import { validateImportedAssetSnapshotList } from '@/features/portfolio';

describe('validateImportedAssetSnapshotList', () => {
  it('rejects empty input', () => {
    const result = validateImportedAssetSnapshotList([]);
    expect(result.valid).toHaveLength(0);
    expect(result.errors).toHaveLength(1);
  });

  it('rejects invalid category/amount/currentPrice', () => {
    const result = validateImportedAssetSnapshotList([
      {
        name: 'A',
        category: 'INVALID' as any,
        amount: 1,
        currentPrice: 100,
        currency: 'KRW',
      },
      {
        name: 'B',
        category: AssetCategory.STOCK_KR,
        amount: 0,
        currentPrice: 100,
        currency: 'KRW',
      },
      {
        name: 'C',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: Number.NaN,
        currency: 'KRW',
      },
    ] as any);

    expect(result.valid).toHaveLength(0);
    expect(result.errors.length).toBeGreaterThanOrEqual(3);
  });

  it('normalizes ticker and infers currency when missing/invalid', () => {
    const result = validateImportedAssetSnapshotList([
      {
        name: '  Apple ',
        ticker: '  AAPL ',
        category: AssetCategory.STOCK_US,
        amount: 1,
        currentPrice: 100,
        currency: 'NOPE' as any,
      },
    ] as any);

    expect(result.errors).toHaveLength(0);
    expect(result.valid[0]?.name).toBe('Apple');
    expect(result.valid[0]?.ticker).toBe('AAPL');
    expect(result.valid[0]?.currency).toBe('USD');
  });

  it('emits warnings for invalid numeric fields and duplicates', () => {
    const result = validateImportedAssetSnapshotList([
      {
        name: 'Samsung',
        ticker: '005930',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: 10,
        purchasePrice: -1,
        realizedProfit: 'x' as any,
        currency: 'KRW',
      },
      {
        name: 'Samsung',
        ticker: '005930',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: 10,
        currency: 'KRW',
      },
    ] as any);

    expect(result.errors).toHaveLength(0);
    expect(result.warnings.length).toBeGreaterThanOrEqual(2);
  });
});
