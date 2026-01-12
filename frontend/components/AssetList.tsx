import React, { useState, useMemo } from 'react';
import { Asset, AssetCategory, TradeType } from '../lib/types';
import type { CmaConfig } from '@/shared/portfolio';
import { Search, Filter, Download, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { AssetEditModal } from './AssetEditModal';
import { AssetRow } from './AssetRow';
import { useAssetExport } from '../hooks/useAssetExport';
import type { ImportedAssetSnapshot } from '@/shared/portfolio';

interface AssetListProps {
  assets: Asset[];
  onDelete: (id: string) => void;
  onTrade: (id: string, type: TradeType, quantity: number, price: number) => void;
  onUpdateAsset: (id: string, updates: {
    name?: string;
    ticker?: string;
    indexGroup?: string;
    category?: AssetCategory;
    amount?: number;
    purchasePrice?: number;
    currentPrice?: number;
  }) => void;
  onUpdateCash: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => void | Promise<void>;
  onRestoreFromBackup?: (snapshot: ImportedAssetSnapshot[]) => Promise<void>;
  onSelectNewsQuery?: (query: string, ticker?: string | null) => void;
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
  onSelectNewsQuery,
  usdFxNow,
  indexGroupOptions,
}) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);

  // Sorting State
  const [sortField, setSortField] = useState<SortField>('valuation');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  // Export/Import 훅
  const {
    fileInputRef,
    isRestoring,
    handleRestoreFromExcelClick,
    handleRestoreFileChange,
    handleDownloadExcel,
  } = useAssetExport({ onRestoreFromBackup });

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
      setSortOrder('desc');
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
              onClick={() => handleDownloadExcel(sortedAssets)}
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
              {sortedAssets.map((asset) => (
                <AssetRow
                  key={asset.id}
                  asset={asset}
                  onDelete={onDelete}
                  onTrade={onTrade}
                  onEdit={setEditingAsset}
                  onSelectNewsQuery={onSelectNewsQuery}
                  getDefaultFxRate={getDefaultFxRate}
                />
              ))}
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
    </div>
  );
};
