
import React from 'react';
import type { TradeRecord } from '../../lib/types';
import { formatCurrency } from '../../lib/utils/constants';

interface TradeItemProps {
    trade: TradeRecord;
}

export const TradeItem: React.FC<TradeItemProps> = ({ trade }) => {
    const isBuy = trade.type === 'BUY';
    const ts = new Date(trade.timestamp);
    const labelTime = ts.toLocaleString('ko-KR', {
        year: '2-digit',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
    const pnl = trade.realizedDelta ?? 0;

    return (
        <li className="py-2 flex items-center justify-between gap-3">
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${isBuy ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600'
                            }`}
                    >
                        {isBuy ? '매수' : '매도'}
                    </span>
                    <span className="text-[11px] text-slate-500">{labelTime}</span>
                </div>
                <div className="mt-0.5 text-[13px] text-slate-800 truncate">
                    {trade.assetName}
                    {trade.ticker && (
                        <span className="ml-1 text-[10px] text-slate-500">
                            ({trade.ticker})
                        </span>
                    )}
                </div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                    {trade.quantity.toLocaleString()}개 @ {formatCurrency(trade.price)}
                </div>
            </div>

            {!isBuy ? (
                <div
                    className={`text-right text-[11px] font-semibold ${pnl > 0
                        ? 'text-red-500'
                        : pnl < 0
                            ? 'text-blue-500'
                            : 'text-slate-400'
                        }`}
                >
                    {pnl > 0 ? '+' : pnl < 0 ? '-' : ''}
                    {formatCurrency(Math.abs(pnl))}
                </div>
            ) : (
                <div className="text-right text-[11px] text-slate-300 font-semibold">-</div>
            )}
        </li>
    );
};
