import React, { useState } from 'react';
import { Asset, AssetCategory, TradeType } from '../types';
import { formatCurrency } from '../constants';
import { Trash2, Search, Filter, Download, Edit3 } from 'lucide-react';

interface AssetListProps {
  assets: Asset[];
  onDelete: (id: string) => void;
  onTrade: (id: string, type: TradeType, quantity: number, price: number) => void;
  onUpdateTicker: (id: string, ticker?: string) => void;
}

export const AssetList: React.FC<AssetListProps> = ({ assets, onDelete, onTrade, onUpdateTicker }) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
   const [activeTradeId, setActiveTradeId] = useState<string | null>(null);
   const [tradeType, setTradeType] = useState<TradeType>('BUY');
   const [tradeQuantity, setTradeQuantity] = useState<string>('');
   const [tradePrice, setTradePrice] = useState<string>('');

  const filteredAssets = assets.filter(asset => {
    const matchesCategory = filter === 'ALL' || asset.category === filter;
    const matchesSearch = asset.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          (asset.ticker || '').toLowerCase().includes(searchTerm.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const categories = ['ALL', ...Object.values(AssetCategory)];

  const handleDownloadExcel = () => {
    // Excel requires BOM (\uFEFF) for correct Korean character encoding
    const BOM = '\uFEFF';
    const headers = ['자산명', '티커', '카테고리', '수량', '매수평균가', '현재가', '평가금액', '실현손익', '수익률(%)'];
    
    const csvRows = filteredAssets.map(asset => {
      const profitRate = asset.purchasePrice 
        ? ((asset.currentPrice - asset.purchasePrice) / asset.purchasePrice) * 100 
        : 0;
      
      const safeName = asset.name.replace(/"/g, '""');
      const safeTicker = (asset.ticker || '').replace(/"/g, '""');

      return [
        `"${safeName}"`,
        `"${safeTicker}"`,
        asset.category,
        asset.amount,
        asset.purchasePrice || 0,
        asset.currentPrice,
        asset.amount * asset.currentPrice,
        asset.realizedProfit || 0,
        profitRate.toFixed(2)
      ].join(',');
    });

    const csvString = BOM + [headers.join(','), ...csvRows].join('\n');
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    
    // Format date for filename: YYYYMMDD
    const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    link.setAttribute('href', url);
    link.setAttribute('download', `portfolio_backup_${dateStr}.csv`);
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const openTrade = (asset: Asset, type: TradeType) => {
    setActiveTradeId(asset.id);
    setTradeType(type);
    setTradeQuantity('');
    setTradePrice(asset.currentPrice.toString());
  };

  const closeTrade = () => {
    setActiveTradeId(null);
    setTradeQuantity('');
    setTradePrice('');
  };

  const submitTrade = (asset: Asset) => {
    const qty = Number(tradeQuantity);
    const price = Number(tradePrice);
    if (Number.isNaN(qty) || Number.isNaN(price)) {
      alert('수량과 가격을 올바르게 입력해주세요.');
      return;
    }
    onTrade(asset.id, tradeType, qty, price);
    closeTrade();
  };

  const handleEditTicker = (asset: Asset) => {
    const current = asset.ticker || '';
    const next = window.prompt('티커를 입력하세요 (예: 005930.KS, AAPL)', current);
    if (next === null) return;
    const trimmed = next.trim();
    onUpdateTicker(asset.id, trimmed || undefined);
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 flex flex-col h-full overflow-hidden pb-20 md:pb-0">
      <div className="p-6 border-b border-slate-100">
        <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold text-slate-800">보유 자산 목록</h2>
            <button 
                onClick={handleDownloadExcel}
                className="flex items-center space-x-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors shadow-sm"
                title="엑셀(CSV)로 다운로드"
            >
                <Download size={16} />
                <span className="hidden md:inline">엑셀 다운로드</span>
                <span className="md:hidden">저장</span>
            </button>
        </div>
        
        <div className="flex flex-col md:flex-row gap-4 justify-between">
           {/* Search */}
           <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-400" size={18} />
            <input 
                type="text" 
                placeholder="자산명, 티커 검색..." 
                className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
            />
           </div>

           {/* Filter Tabs (Horizontal Scroll on Mobile) */}
           <div className="flex overflow-x-auto pb-2 md:pb-0 gap-2 hide-scrollbar">
                {categories.map(cat => (
                    <button
                        key={cat}
                        onClick={() => setFilter(cat)}
                        className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                            filter === cat 
                            ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200' 
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                    >
                        {cat === 'ALL' ? '전체' : cat}
                    </button>
                ))}
           </div>
        </div>
      </div>

      <div className="overflow-auto flex-1">
        {filteredAssets.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-400">
                <Filter size={48} className="mb-4 opacity-20" />
                <p>검색 결과가 없습니다.</p>
            </div>
        ) : (
            <table className="w-full text-left border-collapse min-w-[800px]">
            <thead className="bg-slate-50 sticky top-0 z-10">
                <tr>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider">자산명</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">수량</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">매수평균가</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">현재가</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">평가금액</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">실현손익</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">매수/매도</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">관리</th>
                </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
                {filteredAssets.map((asset) => {
                    const totalValue = asset.amount * asset.currentPrice;
                    const profitRate = asset.purchasePrice 
                        ? ((asset.currentPrice - asset.purchasePrice) / asset.purchasePrice) * 100 
                        : 0;
                    const isProfitable = profitRate > 0;
                    const isLoss = profitRate < 0;
                    const realized = asset.realizedProfit || 0;

                    return (
                      <>
                        <tr key={asset.id} className="hover:bg-slate-50 transition-colors group">
                            <td className="p-4">
                                <div>
                                    <div className="flex items-center space-x-2">
                                        <p className="font-semibold text-slate-800">{asset.name}</p>
                                        {asset.ticker && (
                                            <span className="text-[10px] bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded font-mono">
                                                {asset.ticker}
                                            </span>
                                        )}
                                    </div>
                                    <span className="inline-block px-2 py-0.5 rounded text-[10px] bg-slate-100 text-slate-500 mt-1">
                                        {asset.category}
                                    </span>
                                </div>
                            </td>
                            <td className="p-4 text-right text-slate-600 font-medium">
                                {asset.amount.toLocaleString()}
                            </td>
                            <td className="p-4 text-right text-slate-500">
                                {formatCurrency(asset.purchasePrice || 0)}
                            </td>
                            <td className="p-4 text-right">
                                <div className="text-slate-800 font-medium">{formatCurrency(asset.currentPrice)}</div>
                                {asset.purchasePrice && asset.purchasePrice > 0 && (
                                  <div className={`text-xs ${isProfitable ? 'text-red-500' : isLoss ? 'text-blue-500' : 'text-slate-400'}`}>
                                      {isProfitable ? '+' : ''}{profitRate.toFixed(2)}%
                                  </div>
                                )}
                            </td>
                            <td className="p-4 text-right font-bold text-slate-800">
                                {formatCurrency(totalValue)}
                            </td>
                            <td className="p-4 text-right">
                              <div className={`font-medium ${realized > 0 ? 'text-red-500' : realized < 0 ? 'text-blue-500' : 'text-slate-500'}`}>
                                {realized > 0 ? '+' : ''}{formatCurrency(Math.abs(realized))}
                              </div>
                            </td>
                            <td className="p-4 text-center">
                              <div className="flex items-center justify-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => openTrade(asset, 'BUY')}
                                  className="px-2 py-1 rounded-lg text-[11px] font-medium bg-red-50 text-red-600 hover:bg-red-100"
                                >
                                  매수
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openTrade(asset, 'SELL')}
                                  className="px-2 py-1 rounded-lg text-[11px] font-medium bg-blue-50 text-blue-600 hover:bg-blue-100"
                                >
                                  매도
                                </button>
                              </div>
                            </td>
                            <td className="p-4 text-center">
                              <div className="flex items-center justify-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => handleEditTicker(asset)}
                                  className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-all"
                                  title="티커 수정"
                                >
                                  <Edit3 size={16} />
                                </button>
                                <button 
                                  onClick={() => onDelete(asset.id)}
                                  className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-all"
                                  title="자산 삭제"
                                >
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </td>
                        </tr>
                        {activeTradeId === asset.id && (
                          <tr className="bg-slate-50">
                            <td colSpan={8} className="p-4">
                              <div className="flex flex-col md:flex-row md:items-end gap-3 text-sm">
                                <div className="font-medium text-slate-700">
                                  {asset.name}{' '}
                                  {asset.ticker && (
                                    <span className="text-[11px] text-slate-500 ml-1">
                                      ({asset.ticker})
                                    </span>
                                  )}
                                  <span className="ml-2 text-[11px] px-2 py-0.5 rounded bg-slate-200 text-slate-600">
                                    {tradeType === 'BUY' ? '매수' : '매도'}
                                  </span>
                                </div>
                                <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3">
                                  <div>
                                    <label className="block text-[11px] text-slate-500 mb-1">수량</label>
                                    <input
                                      type="number"
                                      min="0"
                                      step="any"
                                      className="w-full px-3 py-1.5 rounded-lg border border-slate-200 text-sm"
                                      value={tradeQuantity}
                                      onChange={(e) => setTradeQuantity(e.target.value)}
                                    />
                                  </div>
                                  <div>
                                    <label className="block text-[11px] text-slate-500 mb-1">가격</label>
                                    <input
                                      type="number"
                                      min="0"
                                      step="any"
                                      className="w-full px-3 py-1.5 rounded-lg border border-slate-200 text-sm"
                                      value={tradePrice}
                                      onChange={(e) => setTradePrice(e.target.value)}
                                    />
                                  </div>
                                  <div className="md:col-span-2 flex items-center gap-2 mt-2 md:mt-0">
                                    <button
                                      type="button"
                                      onClick={() => submitTrade(asset)}
                                      className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700"
                                    >
                                      적용
                                    </button>
                                    <button
                                      type="button"
                                      onClick={closeTrade}
                                      className="px-3 py-1.5 rounded-lg bg-slate-100 text-slate-600 text-sm hover:bg-slate-200"
                                    >
                                      취소
                                    </button>
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                })}
            </tbody>
            </table>
        )}
      </div>
      
      {/* Mobile Card View hint */}
      <div className="md:hidden p-2 text-center text-xs text-slate-400 bg-slate-50 border-t border-slate-100">
         좌우로 스크롤하여 상세 정보를 확인하세요
      </div>
    </div>
  );
};
