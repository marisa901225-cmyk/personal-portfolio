export const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#10b981', '#3b82f6'];

// 실제 히스토리 연동 전까지는 빈 배열로 두고, 향후 백엔드 스냅샷 데이터로 교체 예정.
export const MOCK_HISTORY_DATA: { date: string; value: number }[] = [];

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
