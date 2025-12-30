import { useEffect, useState } from 'react';
import { AppSettings, DividendEntry } from '../types';
import { alertError } from '../errors';
import { ApiClient, BackendSettings } from '../backendClient';

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
  benchmarkName: undefined,
  benchmarkReturn: undefined,
};

export const useSettings = () => {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  const saveSettingsToServer = async (current: AppSettings): Promise<void> => {
    if (!current.serverUrl || !current.apiToken) {
      return;
    }

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
      usd_fx_base: current.usdFxBase ?? null,
      usd_fx_now: current.usdFxNow ?? null,
      benchmark_name: current.benchmarkName ?? null,
      benchmark_return: current.benchmarkReturn ?? null,
    };

    try {
      const apiClient = new ApiClient(current.serverUrl, current.apiToken);
      const data: BackendSettings = await apiClient.updateSettings(payload);
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

      if (data.usd_fx_base !== undefined || data.usd_fx_now !== undefined) {
        setSettings((prev) => ({
          ...prev,
          usdFxBase: data.usd_fx_base ?? undefined,
          usdFxNow: data.usd_fx_now ?? undefined,
        }));
      }

      if (data.benchmark_name !== undefined || data.benchmark_return !== undefined) {
        setSettings((prev) => ({
          ...prev,
          benchmarkName: data.benchmark_name ?? undefined,
          benchmarkReturn: data.benchmark_return ?? undefined,
        }));
      }
    } catch (error) {
      alertError('Save settings error', error, {
        default: '서버와 통신 중 오류가 발생했습니다.\n설정이 서버에 저장되지 않았을 수 있습니다.',
        unauthorized: '설정을 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
        network: '서버와 통신할 수 없습니다.\n설정이 서버에 저장되지 않았을 수 있습니다.',
      });
    }
  };

  useEffect(() => {
    if (!settings.serverUrl || !settings.apiToken) {
      return;
    }

    const load = async () => {
      try {
        const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);
        const data: BackendSettings = await apiClient.fetchSettings();
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

        if (data.usd_fx_base !== undefined || data.usd_fx_now !== undefined) {
          setSettings((prev) => ({
            ...prev,
            usdFxBase: data.usd_fx_base ?? undefined,
            usdFxNow: data.usd_fx_now ?? undefined,
          }));
        }

        if (data.benchmark_name !== undefined || data.benchmark_return !== undefined) {
          setSettings((prev) => ({
            ...prev,
            benchmarkName: data.benchmark_name ?? undefined,
            benchmarkReturn: data.benchmark_return ?? undefined,
          }));
        }
      } catch (error) {
        alertError('Failed to load settings from server', error, {
          default: '설정을 불러오지 못했습니다.\n서버 상태를 확인해주세요.',
          unauthorized: '설정을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '설정을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        });
      }
    };

    void load();
  }, [settings.serverUrl, settings.apiToken]);

  useEffect(() => {
    if (!settings.serverUrl || !settings.apiToken) {
      return;
    }

    let isActive = true;
    const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);

    const fetchFxNow = async () => {
      try {
        const data = await apiClient.fetchUsdKrwFxRate();
        const rateNum = data?.rate;
        if (!rateNum || !Number.isFinite(rateNum)) {
          return;
        }
        if (isActive) {
          setSettings((prev) => ({
            ...prev,
            usdFxNow: rateNum,
          }));
        }
      } catch {
        // 자동 갱신 실패는 조용히 무시
      }
    };

    void fetchFxNow();
    const interval = window.setInterval(fetchFxNow, 10 * 60 * 1000);
    return () => {
      isActive = false;
      window.clearInterval(interval);
    };
  }, [settings.serverUrl, settings.apiToken]);

  return { settings, setSettings, saveSettingsToServer };
};
