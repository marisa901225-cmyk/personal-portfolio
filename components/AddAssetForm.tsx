import React, { useState } from 'react';
import { Asset, AssetCategory } from '../types';
import { X } from 'lucide-react';

interface AddAssetFormProps {
  onSave: (asset: Asset) => void;
  onCancel: () => void;
  serverUrl?: string;
  apiToken?: string;
}

export const AddAssetForm: React.FC<AddAssetFormProps> = ({ onSave, onCancel, serverUrl, apiToken }) => {
  const [formData, setFormData] = useState<Partial<Asset>>({
    name: '',
    ticker: '',
    category: AssetCategory.STOCK_KR,
    amount: 0,
    currentPrice: 0,
    purchasePrice: 0,
    currency: 'KRW',
    indexGroup: ''
  });
  const [isResolvingTicker, setIsResolvingTicker] = useState(false);
  const [tickerHint, setTickerHint] = useState<string | null>(null);

  const handleChange = (field: keyof Asset, value: any) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.amount || !formData.currentPrice) return;

    const newAsset: Asset = {
      id: Date.now().toString(),
      name: formData.name,
      ticker: formData.ticker,
      category: formData.category as AssetCategory,
      amount: Number(formData.amount),
      currentPrice: Number(formData.currentPrice),
      // If purchasePrice is not entered, assume it matches currentPrice (bought now)
      purchasePrice: Number(formData.purchasePrice) || Number(formData.currentPrice),
      currency: 'KRW',
      realizedProfit: 0,
      indexGroup: formData.indexGroup?.trim() || undefined
    };
    onSave(newAsset);
  };

  const handleResolveTicker = async () => {
    if (!serverUrl) {
      alert('먼저 환경 설정에서 홈서버 URL을 입력해주세요.');
      return;
    }
    if (!formData.name || !formData.name.trim()) {
      alert('종목명을 먼저 입력해주세요.');
      return;
    }

    setIsResolvingTicker(true);
    setTickerHint(null);

    try {
      const headers: HeadersInit = {};
      if (apiToken) {
        headers['X-API-Token'] = apiToken;
      }

      const response = await fetch(
        `${serverUrl}/api/search_ticker?q=${encodeURIComponent(formData.name.trim())}`,
        { headers }
      );
      if (!response.ok) {
        if (response.status === 401) {
          alert('API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.');
          return;
        }

        if (response.status === 429) {
          alert('시세 제공자가 너무 많은 요청을 받아 잠시 차단했습니다.\n잠시 후 다시 시도해주세요.');
          return;
        }

        if (response.status >= 500 && response.status < 600) {
          alert('홈서버 또는 시세 제공자에서 오류가 발생했습니다.\n잠시 후 다시 시도해주세요.');
          return;
        }

        alert(`티커 검색에 실패했습니다. (HTTP ${response.status})`);
        return;
      }
      const data = await response.json();

      if (!data.results || data.results.length === 0) {
        alert('해당 종목명을 찾지 못했습니다. 티커를 직접 입력해주세요.');
        return;
      }

      const best = data.results[0];
      handleChange('ticker', best.symbol);
      setTickerHint(`${best.name} (${best.symbol}${best.exchange ? `, ${best.exchange}` : ''})`);
    } catch (error) {
      console.error('Ticker resolve error:', error);
      alert('티커 자동 조회 중 오류가 발생했습니다. 나중에 다시 시도해주세요.');
    } finally {
      setIsResolvingTicker(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 max-w-2xl mx-auto animate-fade-in-up">
      <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-4">
        <h2 className="text-xl font-bold text-slate-800">새 자산 추가</h2>
        <button onClick={onCancel} className="text-slate-400 hover:text-slate-600">
          <X size={24} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">자산 종류</label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.values(AssetCategory).map(cat => (
              <button
                key={cat}
                type="button"
                onClick={() => handleChange('category', cat)}
                className={`py-2 px-3 rounded-lg text-sm border transition-all ${
                  formData.category === cat
                    ? 'border-indigo-600 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border-slate-200 text-slate-600 hover:border-indigo-300'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">자산명</label>
            <input
                type="text"
                required
                className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
                placeholder="예: 삼성전자"
                value={formData.name}
                onChange={(e) => handleChange('name', e.target.value)}
            />
            </div>
            <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-slate-700">
                티커/종목코드 (선택)
              </label>
              <button
                type="button"
                onClick={handleResolveTicker}
                disabled={isResolvingTicker}
                className={`text-[11px] px-2 py-1 rounded-md border text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors ${
                  isResolvingTicker ? 'opacity-60 cursor-not-allowed' : ''
                }`}
              >
                {isResolvingTicker ? '조회 중...' : '자동 채우기'}
              </button>
            </div>
            <input
                type="text"
                className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors uppercase"
                placeholder="예: 005930, NAS:AAPL"
                value={formData.ticker || ''}
                onChange={(e) => handleChange('ticker', e.target.value)}
            />
            {tickerHint && (
              <p className="text-[10px] text-slate-500 mt-1">
                자동 선택: {tickerHint}
              </p>
            )}
            <p className="text-[10px] text-slate-400 mt-1">
              홈서버 연동 시 사용됩니다 (국내: 6자리 종목코드, 해외: EXCD:티커 형식, 예: NAS:AAPL)
            </p>
            </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">
            지수 그룹 (선택)
          </label>
          <input
            type="text"
            className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
            placeholder="예: S&P500, NASDAQ100, KOSPI200"
            value={formData.indexGroup || ''}
            onChange={(e) => handleChange('indexGroup', e.target.value)}
          />
          <p className="text-[11px] text-slate-400 mt-1">
            같은 지수에 묶인 국내/해외 ETF를 함께 관리할 때 사용합니다.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">수량</label>
            <input
              type="number"
              required
              min="0"
              step="any"
              className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
              placeholder="0"
              value={formData.amount || ''}
              onChange={(e) => handleChange('amount', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">현재 단가 (KRW)</label>
            <input
              type="number"
              required
              min="0"
              className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
              placeholder="0"
              value={formData.currentPrice || ''}
              onChange={(e) => handleChange('currentPrice', e.target.value)}
            />
          </div>
        </div>

        <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">매수 평균가 (선택)</label>
            <input
              type="number"
              min="0"
              className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors"
              placeholder="입력 시 수익률이 계산됩니다."
              value={formData.purchasePrice || ''}
              onChange={(e) => handleChange('purchasePrice', e.target.value)}
            />
            <p className="text-xs text-slate-500 mt-1">
                * 입력하지 않으면 현재가와 동일하게 설정됩니다.
            </p>
        </div>

        <div className="pt-4 flex gap-4">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 py-3 px-4 bg-slate-100 text-slate-700 rounded-xl font-medium hover:bg-slate-200 transition-colors"
          >
            취소
          </button>
          <button
            type="submit"
            className="flex-1 py-3 px-4 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all transform hover:scale-[1.02]"
          >
            자산 추가하기
          </button>
        </div>
      </form>
    </div>
  );
};
