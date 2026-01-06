
import React from 'react';
import type { TradeRecord } from '../../lib/types';
import { TradeItem } from './TradeItem';

interface TradeListProps {
    trades: TradeRecord[];
    isLoadingMore: boolean;
    hasMore: boolean;
    onLoadMore: () => void;
    totalCount: number;
}

export const TradeList: React.FC<TradeListProps> = ({
    trades,
    isLoadingMore,
    hasMore,
    onLoadMore,
    totalCount,
}) => {
    if (trades.length === 0) {
        return (
            <div className="mt-4 text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
                조건에 맞는 거래가 없습니다.
            </div>
        );
    }

    return (
        <div className="mt-3">
            <ul className="divide-y divide-slate-100 text-xs max-h-[420px] overflow-y-auto">
                {trades.map((trade) => (
                    <TradeItem key={trade.id} trade={trade} />
                ))}
            </ul>

            <div className="mt-3 flex items-center justify-between gap-2">
                <div className="text-xs text-slate-400">
                    표시된 거래 {trades.length.toLocaleString()}건
                    {totalCount > trades.length && (
                        <span className="ml-1">
                            (전체 로드된 {totalCount.toLocaleString()}건 중)
                        </span>
                    )}
                </div>

                <button
                    type="button"
                    onClick={onLoadMore}
                    disabled={isLoadingMore || !hasMore}
                    className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                >
                    {isLoadingMore ? '불러오는 중...' : hasMore ? '더 불러오기' : '끝'}
                </button>
            </div>
        </div>
    );
};
