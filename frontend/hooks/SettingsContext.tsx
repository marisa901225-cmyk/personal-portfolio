import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { AppSettings } from '../lib/types';
import { alertError } from '@/shared/errors';
import { ApiClient, BackendSettings } from '@/shared/api/client';

// 보안상의 이유로 apiToken은 메모리(state)에만 저장
// localStorage 저장 제거됨 - 페이지 새로고침 시 토큰 초기화

const DEFAULT_SETTINGS: AppSettings = {
    serverUrl: 'https://dlckdgn-nucboxg3-plus.tail5c2348.ts.net',
    targetIndexAllocations: [
        { indexGroup: 'S&P500', targetWeight: 6 },
        { indexGroup: 'NASDAQ100', targetWeight: 3 },
        { indexGroup: 'BOND+ETC', targetWeight: 1 },
    ],
    usdFxBase: undefined,
    usdFxNow: undefined,
    benchmarkName: undefined,
    benchmarkReturn: undefined,
};

interface SettingsContextValue {
    settings: AppSettings;
    setSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
    saveSettingsToServer: (current: AppSettings) => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
    // apiToken은 메모리에만 저장 (보안상 localStorage 사용 안 함)
    const [settings, setSettings] = useState<AppSettings>({
        ...DEFAULT_SETTINGS,
        apiToken: undefined,
    });

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

    // 설정 로드 (서버에서)
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

    // FX 환율 자동 갱신
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

    return (
        <SettingsContext.Provider value={{ settings, setSettings, saveSettingsToServer }}>
            {children}
        </SettingsContext.Provider>
    );
}

export function useSettings(): SettingsContextValue {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
}
