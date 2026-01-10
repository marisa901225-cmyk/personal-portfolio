
import React, { useState, useMemo, useEffect } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useInfiniteTradesQuery } from '../../src/shared/api/queries/useTradesQuery';
import { useApiClient } from '../../src/shared/api/apiClient';
import { TradeFilters, type TradeFilter } from './TradeFilters';
import { TradeList } from './TradeList';
import type { Asset, TradeRecord } from '../../lib/types';
import { getUserErrorMessage } from '../../lib/utils/errors';

export type TradeHistoryVariant = 'page' | 'collapsible';

export interface TradeHistoryProps {
    assets: Asset[];
    serverUrl: string;
    apiToken?: string;
    variant?: TradeHistoryVariant;
}

export const TradeHistory: React.FC<TradeHistoryProps> = ({
    assets,
    serverUrl,
    apiToken,
    variant = 'page',
}) => {
    const isCollapsible = variant === 'collapsible';
    const [isOpen, setIsOpen] = useState(!isCollapsible);

    // Local filter states
    const [searchTerm, setSearchTerm] = useState('');
    const [tradeFilter, setTradeFilter] = useState<TradeFilter>('ALL');
    const [yearFilter, setYearFilter] = useState<number | 'ALL'>('ALL');
    const [monthFilter, setMonthFilter] = useState<number | 'ALL'>('ALL');

    const isRemoteEnabled = Boolean(serverUrl && apiToken);
    const apiClient = useApiClient({ serverUrl, apiToken });
    const shouldFetch = isRemoteEnabled && (isOpen || !isCollapsible);

    // Use the new unified API hook
    const query = useInfiniteTradesQuery(
        shouldFetch ? apiClient : null,
        assets
    );

    const trades: TradeRecord[] = query.data?.trades ?? [];
    const isLoading = query.isLoading;
    const isError = query.isError;
    const error = query.error;
    const fetchNextPage = query.fetchNextPage;
    const hasNextPage = query.hasNextPage ?? false;
    const isFetchingNextPage = query.isFetchingNextPage;
    const refetch = query.refetch;

    // Calculate available years from loaded trades
    const availableYears = useMemo(() => {
        const years = new Set<number>();
        trades.forEach((trade) => {
            const year = new Date(trade.timestamp).getFullYear();
            years.add(year);
        });
        return Array.from(years).sort((a, b) => b - a);
    }, [trades]);

    // Apply client-side filters
    const filteredTrades = useMemo(() => {
        const query = searchTerm.trim().toLowerCase();
        return trades.filter((trade) => {
            if (tradeFilter !== 'ALL' && trade.type !== tradeFilter) return false;

            const tradeDate = new Date(trade.timestamp);
            if (yearFilter !== 'ALL' && tradeDate.getFullYear() !== yearFilter) return false;
            if (monthFilter !== 'ALL' && (tradeDate.getMonth() + 1) !== monthFilter) return false;

            if (!query) return true;
            const name = trade.assetName.toLowerCase();
            const ticker = (trade.ticker || '').toLowerCase();
            return name.includes(query) || ticker.includes(query);
        });
    }, [trades, tradeFilter, searchTerm, yearFilter, monthFilter]);

    // Auto-open logic (matches original behavior essentially, but simplified)
    useEffect(() => {
        if (!isCollapsible) {
            setIsOpen(true);
        }
    }, [isCollapsible]);

    const loadError = isError
        ? getUserErrorMessage(error, {
            default: '거래 내역을 불러오지 못했습니다.',
            unauthorized: '거래 내역을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
            network: '거래 내역을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        })
        : null;

    return (
        <section className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h2 className="text-sm font-semibold text-slate-800">전체 거래 내역</h2>
                    <p className="text-xs text-slate-500 mt-0.5">
                        {isRemoteEnabled ? '과거 거래까지 페이지로 불러옵니다.' : '서버 연결이 필요합니다. (설정/로그인)'}
                    </p>
                </div>
                {isCollapsible && (
                    <button
                        type="button"
                        onClick={() => setIsOpen((prev) => !prev)}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 transition-colors"
                    >
                        {isOpen ? '닫기' : '열기'}
                        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </button>
                )}
            </div>

            {isOpen && (
                <div className="mt-4">
                    {!isRemoteEnabled ? (
                        <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
                            전체 거래 내역은 백엔드 서버 연결 시에만 조회할 수 있어요.
                        </div>
                    ) : (
                        <>
                            <TradeFilters
                                searchTerm={searchTerm}
                                onSearchChange={setSearchTerm}
                                yearFilter={yearFilter}
                                onYearChange={setYearFilter}
                                monthFilter={monthFilter}
                                onMonthChange={setMonthFilter}
                                tradeFilter={tradeFilter}
                                onTradeFilterChange={setTradeFilter}
                                availableYears={availableYears}
                                onRefresh={refetch}
                                isRefreshing={isLoading && !isFetchingNextPage && trades.length === 0}
                            />

                            {loadError && (
                                <div
                                    role="alert"
                                    className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3"
                                >
                                    {loadError}
                                </div>
                            )}

                            <TradeList
                                trades={filteredTrades}
                                isLoadingMore={isFetchingNextPage}
                                hasMore={hasNextPage}
                                onLoadMore={fetchNextPage}
                                totalCount={trades.length}
                            />
                        </>
                    )}
                </div>
            )}
        </section>
    );
};
