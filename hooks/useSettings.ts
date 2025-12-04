import { useEffect, useState } from 'react';
import { AppSettings, DividendEntry } from '../types';

const SETTINGS_STORAGE_KEY = 'myportfolio_settings';

const DEFAULT_SETTINGS: AppSettings = {
  serverUrl: 'https://dlckdgn-nucboxg3-plus.tail5c2348.ts.net',
  targetIndexAllocations: [
    { indexGroup: 'S&P500', targetWeight: 6 },
    { indexGroup: 'NASDAQ100', targetWeight: 3 },
    { indexGroup: 'BOND+ETC', targetWeight: 1 },
  ],
  usdFxBase: undefined,
  usdFxNow: undefined,
  dividendTotalYear: undefined,
  dividendYear: undefined,
  dividends: [],
};

interface BackendTargetIndexAllocation {
  index_group: string;
  target_weight: number;
}

interface BackendDividend {
  year: number;
  total: number;
}

interface BackendSettings {
  target_index_allocations?: BackendTargetIndexAllocation[];
  server_url?: string | null;
  dividend_year?: number | null;
  dividend_total?: number | null;
  dividends?: BackendDividend[] | null;
}

export const useSettings = () => {
  const [settings, setSettings] = useState<AppSettings>(() => {
    if (typeof window === 'undefined') {
      return DEFAULT_SETTINGS;
    }
    try {
      const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!raw) return DEFAULT_SETTINGS;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return DEFAULT_SETTINGS;
      const merged: AppSettings = {
        ...DEFAULT_SETTINGS,
        ...parsed,
      };
      return merged;
    } catch {
      return DEFAULT_SETTINGS;
    }
  });

  const saveSettingsToServer = async (current: AppSettings): Promise<void> => {
    if (!current.serverUrl || !current.apiToken) {
      return;
    }
    const baseUrl = current.serverUrl.replace(/\/+$/, '');

    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      'X-API-Token': current.apiToken,
    };

    const payload = {
      target_index_allocations: (current.targetIndexAllocations || [])
        .filter((a) => a.indexGroup && a.targetWeight >= 0)
        .map((a) => ({
          index_group: a.indexGroup,
          target_weight: a.targetWeight,
        })),
      server_url: current.serverUrl,
      dividend_year: current.dividendYear ?? null,
      dividend_total: current.dividendTotalYear ?? null,
      dividends: (current.dividends || []).map((d) => ({
        year: d.year,
        total: d.total,
      })),
    };

    try {
      const resp = await fetch(`${baseUrl}/api/settings`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        console.error('Failed to save settings on server', await resp.text());
        alert('서버에 설정을 저장하지 못했습니다.\n나중에 다시 시도해주세요.');
        return;
      }

      const data: BackendSettings = await resp.json();
      if (Array.isArray(data.target_index_allocations)) {
        const mapped = data.target_index_allocations.map((item) => ({
          indexGroup: item.index_group,
          targetWeight: item.target_weight,
        }));
        setSettings((prev) => ({
          ...prev,
          targetIndexAllocations: mapped,
        }));
      }

      if (typeof data.dividend_year === 'number' || typeof data.dividend_total === 'number') {
        setSettings((prev) => ({
          ...prev,
          dividendYear: data.dividend_year ?? prev.dividendYear,
          dividendTotalYear: data.dividend_total ?? prev.dividendTotalYear,
        }));
      }

      if (Array.isArray(data.dividends)) {
        const mappedDividends: DividendEntry[] = data.dividends.map((d) => ({
          year: d.year,
          total: d.total,
        }));
        setSettings((prev) => ({
          ...prev,
          dividends: mappedDividends,
        }));
      }
    } catch (error) {
      console.error('Save settings error', error);
      alert('서버와 통신 중 오류가 발생했습니다.\n설정이 서버에 저장되지 않았을 수 있습니다.');
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const { apiToken, ...rest } = settings;
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(rest));
    } catch {
      // ignore
    }
  }, [settings]);

  useEffect(() => {
    if (!settings.serverUrl || !settings.apiToken) {
      return;
    }

    const baseUrl = settings.serverUrl.replace(/\/+$/, '');
    const headers: HeadersInit = {
      'X-API-Token': settings.apiToken,
    };

    const load = async () => {
      try {
        const resp = await fetch(`${baseUrl}/api/settings`, {
          method: 'GET',
          headers,
        });

        if (!resp.ok) {
          if (resp.status === 401) {
            alert('설정을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.');
          } else {
            console.warn('Failed to load settings from server', resp.status);
          }
          return;
        }

        const data: BackendSettings = await resp.json();
        if (Array.isArray(data.target_index_allocations)) {
          const mapped = data.target_index_allocations.map((item) => ({
            indexGroup: item.index_group,
            targetWeight: item.target_weight,
          }));
          setSettings((prev) => ({
            ...prev,
            targetIndexAllocations: mapped,
          }));
        }

        if (typeof data.dividend_year === 'number' || typeof data.dividend_total === 'number') {
          setSettings((prev) => ({
            ...prev,
            dividendYear: data.dividend_year ?? prev.dividendYear,
            dividendTotalYear: data.dividend_total ?? prev.dividendTotalYear,
          }));
        }

        if (Array.isArray(data.dividends)) {
          const mappedDividends: DividendEntry[] = data.dividends.map((d) => ({
            year: d.year,
            total: d.total,
          }));
          setSettings((prev) => ({
            ...prev,
            dividends: mappedDividends,
          }));
        }
      } catch (error) {
        console.error('Failed to load settings from server', error);
      }
    };

    void load();
  }, [settings.serverUrl, settings.apiToken]);

  return { settings, setSettings, saveSettingsToServer };
};

