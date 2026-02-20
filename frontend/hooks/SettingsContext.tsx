import React, { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { AppSettings } from '../lib/types';
import { alertError } from '@/shared/errors';
import { ApiClient, BackendSettings } from '@/shared/api/client';
import { safeStorage } from '@/shared/storage';
import { queryClient } from '@/app/providers/QueryProvider';

// 보안상의 이유로 apiToken은 메모리(state)에만 저장
// 쿠키 기반 인증 사용

const DEFAULT_SETTINGS: AppSettings = {
    serverUrl: '',
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

const STORAGE_KEY = 'appSettings'; // Define STORAGE_KEY

export function SettingsProvider({ children }: { children: ReactNode }) {
    // apiToken은 메모리에만 저장 (보안상 localStorage 사용 안 함)
    const [settings, setSettings] = useState<AppSettings>(() => {
        try {
            const storedSettings = safeStorage.getItem('local', STORAGE_KEY);

            let initialSettings = { ...DEFAULT_SETTINGS };

            if (storedSettings) {
                const parsed = JSON.parse(storedSettings);
                // Ensure targetIndexAllocations is an array if it exists
                if (parsed.targetIndexAllocations && !Array.isArray(parsed.targetIndexAllocations)) {
                    parsed.targetIndexAllocations = [];
                }
                initialSettings = { ...initialSettings, ...parsed };
            }

            // 쿠키 기반 인증으로 전환되어 토큰을 저장하지 않음
            return {
                ...initialSettings,
                apiToken: undefined,
                cookieAuth: false,
            };
        } catch (error) {
            console.warn('Failed to load settings from storage:', error);
        }
        return {
            ...DEFAULT_SETTINGS,
            apiToken: undefined,
            cookieAuth: false,
        };
    });
    const previousApiScopeRef = useRef<string | null>(null);

    // 설정 저장 (localStorage에 저장)
    const updateSettings = (action: React.SetStateAction<AppSettings>) => {
        setSettings(prev => {
            const next = typeof action === 'function' ? action(prev) : action;

            try {
                // API 토큰은 보안상 저장하지 않음 (서버 URL과 기타 설정만 저장)
                const { apiToken, cookieAuth, ...toSave } = next;
                safeStorage.setItem('local', STORAGE_KEY, JSON.stringify(toSave));
            } catch (error) {
                console.warn('Storage access failed, settings will not be persisted:', error);
            }
            return next;
        });
    };

    useEffect(() => {
        if (settings.serverUrl) return;
        if (typeof window === 'undefined') return;
        updateSettings((prev) => (
            prev.serverUrl
                ? prev
                : {
                    ...prev,
                    serverUrl: window.location.origin,
                }
        ));
    }, [settings.serverUrl]);

    useEffect(() => {
        const currentScope = `${settings.serverUrl}::${settings.apiToken ?? ''}::${settings.cookieAuth ? 'cookie' : 'no-cookie'}`;
        if (previousApiScopeRef.current === null) {
            previousApiScopeRef.current = currentScope;
            return;
        }
        if (previousApiScopeRef.current !== currentScope) {
            // 서버/인증 컨텍스트가 바뀌면 이전 캐시를 비워 stale asset id로 인한 404를 방지
            queryClient.clear();
            previousApiScopeRef.current = currentScope;
        }
    }, [settings.serverUrl, settings.apiToken, settings.cookieAuth]);

    const saveSettingsToServer = async (current: AppSettings): Promise<void> => {
        // 쿠키 인증 또는 레거시 API 토큰이 있어야 함
        if (!current.serverUrl || (!current.apiToken && !current.cookieAuth)) {
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
        if (!settings.serverUrl || (!settings.apiToken && !settings.cookieAuth)) {
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
    }, [settings.serverUrl, settings.apiToken, settings.cookieAuth]);

    // FX 환율 자동 갱신
    useEffect(() => {
        if (!settings.serverUrl || (!settings.apiToken && !settings.cookieAuth)) {
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
    }, [settings.serverUrl, settings.apiToken, settings.cookieAuth]);

    useEffect(() => {
        if (!settings.serverUrl) {
            setSettings((prev) => ({
                ...prev,
                cookieAuth: false,
            }));
            return;
        }

        let isActive = true;
        const checkCookieAuth = async () => {
            try {
                const response = await fetch(`${settings.serverUrl}/api/auth/naver/profile`, {
                    credentials: 'include',
                });
                if (!isActive) return;
                if (response.ok) {
                    const user = await response.json();
                    setSettings((prev) => ({
                        ...prev,
                        cookieAuth: true,
                        naverUser: user,
                    }));
                } else if (response.status === 401 || response.status === 403) {
                    setSettings((prev) => ({
                        ...prev,
                        cookieAuth: false,
                        naverUser: undefined,
                    }));
                }
            } catch {
                if (!isActive) return;
                setSettings((prev) => ({
                    ...prev,
                    cookieAuth: false,
                }));
            }
        };

        void checkCookieAuth();
        return () => {
            isActive = false;
        };
    }, [settings.serverUrl]);

    return (
        <SettingsContext.Provider value={{ settings, setSettings: updateSettings, saveSettingsToServer }}>
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
