import { Asset, TradeRecord } from './types';

export const STORAGE_KEYS = {
  ASSETS: 'myportfolio_assets',
  TRADES: 'myportfolio_trades',
};

// 브라우저 localStorage에 데이터가 있을 때,
// 캐시/쿠키 정리 전에 엑셀 백업을 권장하는 알림 (세션당 1회)
export const showLocalStorageBackupWarning = () => {
  if (typeof window === 'undefined') return;

  try {
    const alreadyShown = window.sessionStorage.getItem(
      'myportfolio_local_backup_notice_shown',
    );
    if (alreadyShown) return;

    const raw = window.localStorage.getItem(STORAGE_KEYS.ASSETS);
    if (!raw) return;

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return;

    window.sessionStorage.setItem('myportfolio_local_backup_notice_shown', '1');
    alert(
      '이 브라우저의 localStorage에 포트폴리오 데이터가 저장되어 있습니다.\n' +
        '브라우저 캐시/쿠키를 지우기 전에, 자산 목록 화면 우측 상단의 "엑셀 다운로드" 버튼으로 백업 파일을 내려받아 두는 것을 추천합니다.',
    );
  } catch {
    // localStorage/sessionStorage 파싱 오류는 무시
  }
};

// localStorage 백업용 헬퍼 (기존 데이터 마이그레이션/캐시 목적)
export const loadAssetsFromStorage = (): Asset[] => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.ASSETS);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as Asset[];
  } catch {
    return [];
  }
};

export const loadTradesFromStorage = (): TradeRecord[] => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.TRADES);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as TradeRecord[];
  } catch {
    return [];
  }
};

