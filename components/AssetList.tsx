import React, { useState, useMemo, useRef } from 'react';
import { Asset, AssetCategory, TradeType } from '../types';
import type { CmaConfig } from '../cmaConfig';
import { formatCurrency } from '../constants';
import { Trash2, Search, Filter, Download, Edit3, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { AssetEditModal } from './AssetEditModal';
import type { ImportedAssetSnapshot } from '../hooks/portfolioTypes';
import { validateImportedAssetSnapshotList } from '../hooks/portfolioBackupValidation';
import { alertError } from '../errors';

interface AssetListProps {
  assets: Asset[];
  onDelete: (id: string) => void;
  onTrade: (id: string, type: TradeType, quantity: number, price: number) => void;
  onUpdateAsset: (id: string, updates: { ticker?: string; indexGroup?: string }) => void;
  onUpdateCash: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => void | Promise<void>;
  onRestoreFromBackup?: (snapshot: ImportedAssetSnapshot[]) => Promise<void>;
  usdFxNow?: number;
  indexGroupOptions?: string[];
}

type SortField = 'name' | 'amount' | 'purchasePrice' | 'currentPrice' | 'valuation' | 'realizedProfit' | 'profitRate';
type SortOrder = 'asc' | 'desc';

export const AssetList: React.FC<AssetListProps> = ({
  assets,
  onDelete,
  onTrade,
  onUpdateAsset,
  onUpdateCash,
  onRestoreFromBackup,
  usdFxNow,
  indexGroupOptions,
}) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [activeTradeId, setActiveTradeId] = useState<string | null>(null);
  const [tradeType, setTradeType] = useState<TradeType>('BUY');
  const [tradeQuantity, setTradeQuantity] = useState<string>('');
  const [tradePrice, setTradePrice] = useState<string>('');
  const [tradeFxRate, setTradeFxRate] = useState<string>('');
  const [tradeUsdPrice, setTradeUsdPrice] = useState<string>('');
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Sorting State
  const [sortField, setSortField] = useState<SortField>('valuation'); // Default sort by valuation
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc'); // High to Low default

  // 설정에서 현재 환율 가져오기
  const getDefaultFxRate = (): number => {
    if (typeof usdFxNow === 'number' && usdFxNow > 0) {
      return usdFxNow;
    }
    return 0;
  };

  const filteredAssets = useMemo(() => {
    return assets.filter(asset => {
      const matchesCategory = filter === 'ALL' || asset.category === filter;
      const matchesSearch = asset.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (asset.ticker || '').toLowerCase().includes(searchTerm.toLowerCase());
      return matchesCategory && matchesSearch;
    });
  }, [assets, filter, searchTerm]);

  const sortedAssets = useMemo(() => {
    return [...filteredAssets].sort((a, b) => {
      let valA: number | string = 0;
      let valB: number | string = 0;

      switch (sortField) {
        case 'name':
          valA = a.name;
          valB = b.name;
          break;
        case 'amount':
          valA = a.amount;
          valB = b.amount;
          break;
        case 'purchasePrice':
          valA = a.purchasePrice || 0;
          valB = b.purchasePrice || 0;
          break;
        case 'currentPrice':
          valA = a.currentPrice;
          valB = b.currentPrice;
          break;
        case 'valuation':
          valA = a.amount * a.currentPrice;
          valB = b.amount * b.currentPrice;
          break;
        case 'realizedProfit':
          valA = a.realizedProfit || 0;
          valB = b.realizedProfit || 0;
          break;
        default:
          return 0;
      }

      if (typeof valA === 'string' && typeof valB === 'string') {
        return sortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }

      return sortOrder === 'asc' ? (valA as number) - (valB as number) : (valB as number) - (valA as number);
    });
  }, [filteredAssets, sortField, sortOrder]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('desc'); // Default to high-to-low for new number fields usually
    }
  };

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) return <ArrowUpDown size={12} className="ml-1 text-slate-300 opacity-0 group-hover:opacity-50 transition-opacity" />;
    return sortOrder === 'asc'
      ? <ArrowUp size={12} className="ml-1 text-indigo-600" />
      : <ArrowDown size={12} className="ml-1 text-indigo-600" />;
  };

  const SortableHeader = ({ field, label, align = 'left' }: { field: SortField, label: string, align?: 'left' | 'right' | 'center' }) => (
    <th
      className={`p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-${align} cursor-pointer hover:bg-slate-100 transition-colors group select-none`}
      onClick={() => handleSort(field)}
    >
      <div className={`flex items-center ${align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start'}`}>
        {label}
        {renderSortIcon(field)}
      </div>
    </th>
  );

  const categories = ['ALL', ...Object.values(AssetCategory)];

  const parseCsvLine = (line: string): string[] => {
    const result: string[] = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];

      if (inQuotes) {
        if (ch === '"') {
          const next = line[i + 1];
          if (next === '"') {
            current += '"';
            i += 1;
          } else {
            inQuotes = false;
          }
        } else {
          current += ch;
        }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        result.push(current);
        current = '';
      } else {
        current += ch;
      }
    }

    result.push(current);
    return result.map((v) => v.replace(/\r$/, ''));
  };

  const handleRestoreFromExcelClick = () => {
    if (!onRestoreFromBackup) {
      alert('복원 기능이 활성화되어 있지 않습니다.');
      return;
    }
    fileInputRef.current?.click();
  };

  const handleRestoreFileChange: React.ChangeEventHandler<HTMLInputElement> = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!onRestoreFromBackup) return;

    try {
      setIsRestoring(true);
      const text = await file.text();
      const cleaned = text.replace(/^\uFEFF/, '');
      const lines = cleaned
        .split(/\n/)
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

      if (lines.length < 2) {
        alert('엑셀 파일에서 데이터 행을 찾을 수 없습니다.');
        return;
      }

      const header = parseCsvLine(lines[0]).map((h) => h.trim());
      if (!header.includes('자산명') || !header.includes('카테고리')) {
        alert('이 포트폴리오에서 내보낸 형식의 엑셀 파일이 아닙니다.');
        return;
      }

      const dataLines = lines.slice(1);
      const snapshot: ImportedAssetSnapshot[] = [];

      dataLines.forEach((rawLine) => {
        const cols = parseCsvLine(rawLine);
        if (cols.length < 6) {
          return;
        }

        const name = cols[0]?.trim();
        const ticker = cols[1]?.trim() || undefined;
        const categoryRaw = cols[2]?.trim() as AssetCategory | undefined;
        const amount = Number(cols[3]);
        const purchasePrice = Number(cols[4]);
        const currentPrice = Number(cols[5]);
        const realizedProfit = cols[7] != null ? Number(cols[7]) : undefined;

        if (!name || !categoryRaw || Number.isNaN(amount) || amount <= 0 || Number.isNaN(currentPrice)) {
          return;
        }

        const category: AssetCategory = categoryRaw;
        const currency: 'KRW' | 'USD' =
          category === AssetCategory.STOCK_US ? 'USD' : 'KRW';

        snapshot.push({
          name,
          ticker,
          category,
          amount,
          purchasePrice: Number.isNaN(purchasePrice) ? undefined : purchasePrice,
          currentPrice,
          realizedProfit: realizedProfit != null && !Number.isNaN(realizedProfit) ? realizedProfit : undefined,
          currency,
        });
      });

      if (snapshot.length === 0) {
        alert('엑셀 파일에서 유효한 자산 데이터를 찾지 못했습니다.');
        return;
      }

      const validation = validateImportedAssetSnapshotList(snapshot);
      if (validation.errors.length > 0) {
        alert(
          `엑셀 백업 데이터에 문제가 있어 복원을 중단했습니다.\n\n${validation.errors.slice(0, 8).join('\n')}`,
        );
        return;
      }

      if (validation.warnings.length > 0 && typeof window !== 'undefined') {
        const proceed = window.confirm(
          `엑셀 백업 데이터에 경고가 있습니다.\n그래도 복원할까요?\n\n${validation.warnings.slice(0, 8).join('\n')}`,
        );
        if (!proceed) {
          return;
        }
      }

      await onRestoreFromBackup(validation.valid);
    } catch (error) {
      alertError('Restore from Excel error', error, {
        default: '엑셀 파일을 읽는 중 오류가 발생했습니다.\n파일 형식을 확인해주세요.',
      });
    } finally {
      setIsRestoring(false);
    }
  };

  const handleDownloadExcel = () => {
    // Excel requires BOM (\uFEFF) for correct Korean character encoding
    const BOM = '\uFEFF';
    const headers = ['자산명', '티커', '카테고리', '수량', '매수평균가', '현재가', '평가금액', '실현손익', '수익률(%)'];

    // Export sortedAssets to respect user's view
    const csvRows = sortedAssets.map(asset => {
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

    if (asset.category === AssetCategory.STOCK_US) {
      // 해외주식: 환율/달러 단가 입력 모드
      setTradeFxRate('');
      setTradeUsdPrice('');
      setTradePrice('');
    } else {
      // 국내자산: 원화 단가만
      setTradePrice(asset.currentPrice.toString());
      setTradeFxRate('');
      setTradeUsdPrice('');
    }
  };

  const closeTrade = () => {
    setActiveTradeId(null);
    setTradeQuantity('');
    setTradePrice('');
    setTradeFxRate('');
    setTradeUsdPrice('');
  };

  const submitTrade = (asset: Asset) => {
    const qty = Number(tradeQuantity);

    let finalPrice: number;

    if (asset.category === AssetCategory.STOCK_US) {
      // 해외주식: 달러단가 × 환율 = 원화단가
      const usdPrice = Number(tradeUsdPrice);
      const fxRate = tradeFxRate ? Number(tradeFxRate) : getDefaultFxRate();

      if (Number.isNaN(usdPrice) || usdPrice <= 0) {
        alert('달러 단가를 올바르게 입력해주세요.');
        return;
      }
      if (fxRate <= 0) {
        alert('환율을 입력하거나 설정에서 현재환율을 설정해주세요.');
        return;
      }

      finalPrice = usdPrice * fxRate;
    } else {
      // 국내자산: 원화 단가 그대로
      finalPrice = Number(tradePrice);
    }

    if (Number.isNaN(qty) || qty <= 0) {
      alert('수량을 올바르게 입력해주세요.');
      return;
    }
    if (Number.isNaN(finalPrice) || finalPrice <= 0) {
      alert('가격을 올바르게 입력해주세요.');
      return;
    }

    onTrade(asset.id, tradeType, qty, finalPrice);
    closeTrade();
  };

  const handleEditTickerOrCash = (asset: Asset) => {
    setEditingAsset(asset);
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 flex flex-col h-full overflow-hidden pb-20 md:pb-0">
      <div className="p-6 border-b border-slate-100">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold text-slate-800">보유 자산 목록</h2>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={handleRestoreFileChange}
            />
            <button
              type="button"
              onClick={handleRestoreFromExcelClick}
              disabled={isRestoring}
              className="flex items-center space-x-2 px-3 py-2 bg-slate-100 text-slate-700 rounded-lg text-xs font-medium hover:bg-slate-200 transition-colors shadow-sm disabled:opacity-60"
              title="엑셀(CSV)에서 포트폴리오 복원"
            >
              <span className="hidden md:inline">엑셀 복원</span>
              <span className="md:hidden">복원</span>
            </button>
            <button
              type="button"
              onClick={handleDownloadExcel}
              className="flex items-center space-x-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors shadow-sm"
              title="엑셀(CSV)로 다운로드"
            >
              <Download size={16} />
              <span className="hidden md:inline">엑셀 다운로드</span>
              <span className="md:hidden">저장</span>
            </button>
          </div>
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
                className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${filter === cat
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
        {sortedAssets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-400">
            <Filter size={48} className="mb-4 opacity-20" />
            <p>검색 결과가 없습니다.</p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse min-w-[800px]">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr>
                <SortableHeader field="name" label="자산명" />
                <SortableHeader field="amount" label="수량" align="right" />
                <SortableHeader field="purchasePrice" label="매수평균가" align="right" />
                <SortableHeader field="currentPrice" label="현재가" align="right" />
                <SortableHeader field="valuation" label="평가금액" align="right" />
                <SortableHeader field="realizedProfit" label="실현손익" align="right" />
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">매수/매도</th>
                <th className="p-4 text-xs font-semibold text-slate-500 uppercase tracking-wider text-center">관리</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {sortedAssets.map((asset) => {
                const totalValue = asset.amount * asset.currentPrice;
                const profitRate = asset.purchasePrice
                  ? ((asset.currentPrice - asset.purchasePrice) / asset.purchasePrice) * 100
                  : 0;
                const isProfitable = profitRate > 0;
                const isLoss = profitRate < 0;
                const realized = asset.realizedProfit || 0;

                return (
                  <React.Fragment key={asset.id}>
                    <tr className="hover:bg-slate-50 transition-colors group">
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
                            onClick={() => handleEditTickerOrCash(asset)}
                            className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-all"
                            title={asset.category === AssetCategory.CASH ? '예비금 잔액 수정' : '티커 수정'}
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

                              {asset.category === AssetCategory.STOCK_US ? (
                                <>
                                  <div>
                                    <label className="block text-[11px] text-slate-500 mb-1">
                                      환전 환율 <span className="text-slate-400">(비워두면 설정값)</span>
                                    </label>
                                    <input
                                      type="number"
                                      min="0"
                                      step="any"
                                      placeholder={getDefaultFxRate() > 0 ? getDefaultFxRate().toFixed(2) : '환율 입력'}
                                      className="w-full px-3 py-1.5 rounded-lg border border-slate-200 text-sm"
                                      value={tradeFxRate}
                                      onChange={(e) => setTradeFxRate(e.target.value)}
                                    />
                                  </div>
                                  <div>
                                    <label className="block text-[11px] text-slate-500 mb-1">단가 (USD)</label>
                                    <input
                                      type="number"
                                      min="0"
                                      step="any"
                                      className="w-full px-3 py-1.5 rounded-lg border border-slate-200 text-sm"
                                      value={tradeUsdPrice}
                                      onChange={(e) => setTradeUsdPrice(e.target.value)}
                                    />
                                  </div>
                                </>
                              ) : (
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
                              )}

                              <div className="flex items-center gap-2 mt-2 md:mt-0">
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
                  </React.Fragment>
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

      <AssetEditModal
        isOpen={!!editingAsset}
        onClose={() => setEditingAsset(null)}
        asset={editingAsset}
        onUpdateAsset={onUpdateAsset}
        onUpdateCash={onUpdateCash}
        indexGroupOptions={indexGroupOptions}
      />
    </div >
  );
};
