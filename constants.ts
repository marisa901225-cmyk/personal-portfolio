import { Asset, AssetCategory } from './types';

export const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#10b981', '#3b82f6'];

export const INITIAL_ASSETS: Asset[] = [
  {
    id: '1',
    name: '삼성전자',
    ticker: '005930.KS',
    category: AssetCategory.STOCK_KR,
    amount: 150,
    currentPrice: 72000,
    currency: 'KRW',
    purchasePrice: 68000
  },
  {
    id: '2',
    name: 'Apple Inc.',
    ticker: 'AAPL',
    category: AssetCategory.STOCK_US,
    amount: 15,
    currentPrice: 245000, // Approximated KRW for simplicity
    currency: 'KRW',
    purchasePrice: 210000
  },
  {
    id: '3',
    name: '강남 아파트 전세금',
    category: AssetCategory.REAL_ESTATE,
    amount: 1,
    currentPrice: 800000000,
    currency: 'KRW',
    purchasePrice: 800000000
  },
  {
    id: '4',
    name: 'CMA 통장',
    category: AssetCategory.CASH,
    amount: 1,
    currentPrice: 15000000,
    currency: 'KRW',
    purchasePrice: 15000000
  }
];

export const MOCK_HISTORY_DATA = [
  { date: '1월', value: 850000000 },
  { date: '2월', value: 865000000 },
  { date: '3월', value: 862000000 },
  { date: '4월', value: 890000000 },
  { date: '5월', value: 905000000 },
  { date: '6월', value: 938550000 },
];

export const formatCurrency = (value: number) => {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0
  }).format(value);
};

export const formatCompactNumber = (number: number) => {
  const formatter = Intl.NumberFormat("ko-KR", { notation: "compact" });
  return formatter.format(number);
};
