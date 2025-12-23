import { AssetCategory } from './types';

/**
 * 해외주식 거래소 prefix 목록
 * NAS: NASDAQ, NYS: NYSE, AMS: AMEX 등
 */
const FOREIGN_EXCHANGE_PREFIXES = ['NAS:', 'NYS:', 'AMS:', 'HKS:', 'SHS:', 'SZS:', 'TSE:', 'LON:'];

/**
 * 티커 문자열을 보고 자산 카테고리를 추론합니다.
 * @param ticker - 티커 문자열 (예: "NAS:AAPL", "005930")
 * @param currentCategory - 현재 카테고리 (추론 불가 시 fallback)
 * @returns 추론된 카테고리
 */
export function inferCategoryFromTicker(
  ticker: string | undefined,
  currentCategory: AssetCategory
): AssetCategory {
  if (!ticker || ticker.trim() === '') {
    return currentCategory;
  }

  const upperTicker = ticker.toUpperCase().trim();

  // 해외 거래소 prefix 체크
  for (const prefix of FOREIGN_EXCHANGE_PREFIXES) {
    if (upperTicker.startsWith(prefix)) {
      return AssetCategory.STOCK_US;
    }
  }

  // 국내 종목코드: 6자리 숫자
  if (/^\d{6}$/.test(upperTicker)) {
    return AssetCategory.STOCK_KR;
  }

  // 추론 불가 → 현재 카테고리 유지
  return currentCategory;
}
