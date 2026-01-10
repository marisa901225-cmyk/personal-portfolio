import { AssetCategory } from '@lib/types';
import type { ImportedAssetSnapshot } from '@/shared/portfolio';

export type SnapshotValidationResult = {
  valid: ImportedAssetSnapshot[];
  errors: string[];
  warnings: string[];
};

const CATEGORY_VALUES = new Set<string>(Object.values(AssetCategory));

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const normalizeTicker = (ticker: unknown): string | undefined => {
  if (typeof ticker !== 'string') return undefined;
  const trimmed = ticker.trim();
  return trimmed ? trimmed : undefined;
};

const inferCurrency = (category: AssetCategory, currency: unknown): 'KRW' | 'USD' => {
  if (currency === 'KRW' || currency === 'USD') return currency;
  return category === AssetCategory.STOCK_US ? 'USD' : 'KRW';
};

export const validateImportedAssetSnapshotList = (
  snapshot: ImportedAssetSnapshot[],
): SnapshotValidationResult => {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!Array.isArray(snapshot) || snapshot.length === 0) {
    return {
      valid: [],
      errors: ['가져올 자산 데이터가 비어 있습니다.'],
      warnings: [],
    };
  }

  const dedupeKeyCount = new Map<string, number>();
  const valid: ImportedAssetSnapshot[] = snapshot.flatMap((raw, index) => {
    const row = index + 2; // CSV 기준: 1=header, 2부터 데이터

    const name = typeof raw.name === 'string' ? raw.name.trim() : '';
    if (!name) {
      errors.push(`${row}행: 자산명이 비어 있습니다.`);
      return [];
    }

    const categoryRaw = raw.category as unknown;
    if (typeof categoryRaw !== 'string' || !CATEGORY_VALUES.has(categoryRaw)) {
      errors.push(`${row}행: 카테고리가 올바르지 않습니다. (${String(categoryRaw)})`);
      return [];
    }
    const category = categoryRaw as AssetCategory;

    if (!isFiniteNumber(raw.amount) || raw.amount <= 0) {
      errors.push(`${row}행: 수량이 올바르지 않습니다. (${String(raw.amount)})`);
      return [];
    }

    if (!isFiniteNumber(raw.currentPrice) || raw.currentPrice < 0) {
      errors.push(`${row}행: 현재가가 올바르지 않습니다. (${String(raw.currentPrice)})`);
      return [];
    }

    const purchasePrice =
      raw.purchasePrice == null
        ? undefined
        : isFiniteNumber(raw.purchasePrice) && raw.purchasePrice >= 0
          ? raw.purchasePrice
          : undefined;

    if (raw.purchasePrice != null && purchasePrice == null) {
      warnings.push(`${row}행: 매수평균가가 유효하지 않아 무시합니다. (${String(raw.purchasePrice)})`);
    }

    const realizedProfit =
      raw.realizedProfit == null
        ? undefined
        : isFiniteNumber(raw.realizedProfit)
          ? raw.realizedProfit
          : undefined;

    if (raw.realizedProfit != null && realizedProfit == null) {
      warnings.push(`${row}행: 실현손익이 유효하지 않아 무시합니다. (${String(raw.realizedProfit)})`);
    }

    const currency = inferCurrency(category, raw.currency);
    const ticker = normalizeTicker(raw.ticker);

    const key = `${name}|${ticker ?? ''}|${category}|${currency}`;
    dedupeKeyCount.set(key, (dedupeKeyCount.get(key) ?? 0) + 1);

    return [
      {
        name,
        ticker,
        category,
        amount: raw.amount,
        purchasePrice,
        currentPrice: raw.currentPrice,
        realizedProfit,
        currency,
      },
    ];
  });

  const duplicateKeys = Array.from(dedupeKeyCount.entries()).filter(([, count]) => count > 1);
  if (duplicateKeys.length > 0) {
    warnings.push(`중복 자산 ${duplicateKeys.length}건이 있습니다. (동일 자산이 여러 줄로 들어왔을 수 있습니다)`);
  }

  return { valid, errors, warnings };
};
