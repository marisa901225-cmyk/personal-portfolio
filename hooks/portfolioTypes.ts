import { AssetCategory } from '../types';

export interface ImportedAssetSnapshot {
  name: string;
  ticker?: string;
  category: AssetCategory;
  amount: number;
  purchasePrice?: number;
  currentPrice: number;
  realizedProfit?: number;
  currency: 'KRW' | 'USD';
}

