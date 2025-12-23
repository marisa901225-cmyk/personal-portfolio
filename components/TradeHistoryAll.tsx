import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, RefreshCw, Search } from 'lucide-react';
import { ApiClient, BackendTrade, mapBackendTradesToFrontend } from '../backendClient';
import { formatCurrency } from '../constants';
import { getUserErrorMessage } from '../errors';
import type { Asset, TradeRecord, TradeType } from '../types';

type TradeFilter = 'ALL' | TradeType;

type TradeHistoryVariant = 'page' | 'collapsible';

interface TradeHistoryAllProps {
  assets: Asset[];
  serverUrl: string;
  apiToken?: string;
  variant?: TradeHistoryVariant;
}

const PAGE_SIZE = 100;

export const TradeHistoryAll: React.FC<TradeHistoryAllProps> = ({
  assets,
  serverUrl,
  apiToken,
  variant = 'page',
}) => {
  const isCollapsible = variant === 'collapsible';
  const [isOpen, setIsOpen] = useState(!isCollapsible);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [cursorBeforeId, setCursorBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [tradeFilter, setTradeFilter] = useState<TradeFilter>('ALL');

  const isRemoteEnabled = Boolean(serverUrl && apiToken);

  const apiClient = useMemo(() => {
    return new ApiClient(serverUrl, apiToken);
  }, [serverUrl, apiToken]);

  const loadTrades = async ({ reset }: { reset: boolean }) => {
    if (!isRemoteEnabled) return;
    if (isLoading) return;
    if (!hasMore && !reset) return;

    const beforeId = reset ? undefined : cursorBeforeId ?? undefined;

    setIsLoading(true);
    setLoadError(null);

    try {
      const backendTrades = await apiClient.fetchTrades({ limit: PAGE_SIZE, beforeId });
      if (backendTrades.length === 0) {
        setHasMore(false);
        return;
      }

      const mapped = mapBackendTradesToFrontend(backendTrades, assets);
      setTrades((prev) => (reset ? mapped : [...prev, ...mapped]));

      const last: BackendTrade = backendTrades[backendTrades.length - 1];
      setCursorBeforeId(last.id);
      setHasMore(backendTrades.length === PAGE_SIZE);
    } catch (error) {
      setLoadError(
        getUserErrorMessage(error, {
          default: '거래 내역을 불러오지 못했습니다.',
          unauthorized: '거래 내역을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '거래 내역을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async () => {
    setTrades([]);
    setCursorBeforeId(null);
    setHasMore(true);
    await loadTrades({ reset: true });
  };

  useEffect(() => {
    setTrades([]);
    setCursorBeforeId(null);
    setHasMore(true);
    setLoadError(null);
    setIsLoading(false);
  }, [serverUrl, apiToken]);

  useEffect(() => {
    if (isCollapsible && !isOpen) return;
    if (!isRemoteEnabled) return;
    if (trades.length > 0) return;
    void loadTrades({ reset: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, isRemoteEnabled, isCollapsible]);

  const filteredTrades = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return trades.filter((trade) => {
      if (tradeFilter !== 'ALL' && trade.type !== tradeFilter) return false;
      if (!query) return true;
      const name = trade.assetName.toLowerCase();
      const ticker = (trade.ticker || '').toLowerCase();
      return name.includes(query) || ticker.includes(query);
    });
  }, [trades, tradeFilter, searchTerm]);

  const tradeFilters: { key: TradeFilter; label: string }[] = [
    { key: 'ALL', label: '전체' },
    { key: 'BUY', label: '매수' },
    { key: 'SELL', label: '매도' },
  ];

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

      {(!isCollapsible || isOpen) && (
        <div className="mt-4">
          {!isRemoteEnabled ? (
            <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
              전체 거래 내역은 백엔드 서버 연결 시에만 조회할 수 있어요.
            </div>
          ) : (
            <>
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                <div className="relative flex-1 max-w-md">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="자산명/티커 검색..."
                    className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-1">
                    {tradeFilters.map(({ key, label }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setTradeFilter(key)}
                        className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${tradeFilter === key
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                          }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => void handleRefresh()}
                    disabled={isLoading}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
                    새로고침
                  </button>
                </div>
              </div>

              {loadError && (
                <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">
                  {loadError}
                </div>
              )}

              <div className="mt-3">
                {filteredTrades.length === 0 ? (
                  <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
                    {trades.length === 0 ? '거래 내역이 없습니다.' : '조건에 맞는 거래가 없습니다.'}
                  </div>
                ) : (
                  <ul className="divide-y divide-slate-100 text-xs max-h-[420px] overflow-y-auto">
                    {filteredTrades.map((trade) => {
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
                        <li key={trade.id} className="py-2 flex items-center justify-between gap-3">
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
                    })}
                  </ul>
                )}

                <div className="mt-3 flex items-center justify-between gap-2">
                  <div className="text-xs text-slate-400">
                    불러온 거래 {trades.length.toLocaleString()}건
                    {filteredTrades.length !== trades.length && (
                      <span className="ml-1">
                        (표시 {filteredTrades.length.toLocaleString()}건)
                      </span>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => void loadTrades({ reset: false })}
                    disabled={isLoading || !hasMore}
                    className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                  >
                    {isLoading ? '불러오는 중...' : hasMore ? '더 불러오기' : '끝'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
};
