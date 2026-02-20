import React, { useState } from 'react';
import { Asset, AssetCategory } from '../lib/types';
import { X } from 'lucide-react';
import { ApiClient } from '@/shared/api/client';
import { alertError } from '@/shared/errors';
import { inferCategoryFromTicker } from '@/shared/portfolio';
import { cn, ui } from '@/shared/ui';

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

  const isCashCategory = formData.category === AssetCategory.CASH;
  const supportsTicker =
    formData.category === AssetCategory.STOCK_KR || formData.category === AssetCategory.STOCK_US;

  const handleChange = (field: keyof Asset, value: Asset[keyof Asset]) => {
    setFormData(prev => {
      const updated = { ...prev, [field]: value };
      // 티커 변경 시 카테고리 자동 추론
      if (field === 'ticker' && typeof value === 'string') {
        const inferred = inferCategoryFromTicker(value, prev.category || AssetCategory.STOCK_KR);
        if (inferred !== prev.category) {
          updated.category = inferred;
        }
      }
      return updated;
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const isCash = formData.category === AssetCategory.CASH;

    if (!formData.name || !formData.currentPrice || (!isCash && !formData.amount)) {
      return;
    }

    const currentPrice = Number(formData.currentPrice);
    const amount = isCash ? 1 : Number(formData.amount);
    const purchasePrice = isCash
      ? currentPrice
      : Number(formData.purchasePrice) || currentPrice;

    const newAsset: Asset = {
      id: Date.now().toString(),
      name: formData.name,
      ticker: formData.ticker,
      category: formData.category as AssetCategory,
      amount,
      currentPrice,
      // If purchasePrice is not entered, assume it matches currentPrice (bought now)
      purchasePrice,
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
      const client = new ApiClient(serverUrl, apiToken);
      const data = await client.searchTicker(formData.name.trim());
      if (!Array.isArray(data.results) || data.results.length === 0) {
        alert('해당 종목명을 찾지 못했습니다. 티커를 직접 입력해주세요.');
        return;
      }

      const best = data.results[0];
      handleChange('ticker', best.symbol);
      setTickerHint(`${best.name} (${best.symbol}${best.exchange ? `, ${best.exchange}` : ''})`);
    } catch (error) {
      alertError('Ticker resolve error', error, {
        default: '티커 자동 조회 중 오류가 발생했습니다.\n나중에 다시 시도해주세요.',
        unauthorized:
          'API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.',
        rateLimited: '시세 제공자가 너무 많은 요청을 받아 잠시 차단했습니다.\n잠시 후 다시 시도해주세요.',
        network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
      });
    } finally {
      setIsResolvingTicker(false);
    }
  };

  return (
    <div className={cn(ui.card, 'p-6 max-w-2xl mx-auto animate-fade-in-up')}>
      <div className="flex justify-between items-center mb-6 border-b border-slate-100 pb-4">
        <h2 className="text-xl font-bold text-slate-800">새 자산 추가</h2>
        <button onClick={onCancel} className="text-slate-400 hover:text-slate-600">
          <X size={24} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className={ui.label}>자산 종류</label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.values(AssetCategory).map(cat => (
              <button
                key={cat}
                type="button"
                onClick={() => handleChange('category', cat)}
                className={`py-2 px-3 rounded-lg text-sm border transition-all ${formData.category === cat
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
            <label className={ui.label}>자산명</label>
            <input
              type="text"
              required
              className={ui.input}
              placeholder={isCashCategory ? '예: 카카오뱅크 통장' : '예: 삼성전자'}
              value={formData.name}
              onChange={(e) => handleChange('name', e.target.value)}
            />
          </div>
          {supportsTicker && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-slate-700">
                  티커/종목코드 (선택)
                </label>
                <button
                  type="button"
                  onClick={handleResolveTicker}
                  disabled={isResolvingTicker}
                  className={`text-[11px] px-2 py-1 rounded-md border text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors ${isResolvingTicker ? 'opacity-60 cursor-not-allowed' : ''
                    }`}
                >
                  {isResolvingTicker ? '조회 중...' : '자동 채우기'}
                </button>
              </div>
              <input
                type="text"
                className={cn(ui.input, 'uppercase')}
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
          )}
        </div>

        <div>
          <label className={ui.label}>
            지수 그룹 (선택)
          </label>
          <input
            type="text"
            className={ui.input}
            placeholder="예: S&P500, NASDAQ100, KOSPI200"
            value={formData.indexGroup || ''}
            onChange={(e) => handleChange('indexGroup', e.target.value)}
          />
          <p className="text-[11px] text-slate-400 mt-1">
            같은 지수에 묶인 국내/해외 ETF를 함께 관리할 때 사용합니다.
          </p>
        </div>

        {isCashCategory ? (
          <div>
            <label className={ui.label}>
              보유 금액 (KRW)
            </label>
            <input
              type="number"
              required
              min="0"
              step="any"
              className={ui.input}
              placeholder="0"
              value={formData.currentPrice || ''}
              onChange={(e) => handleChange('currentPrice', e.target.value)}
            />
            <p className="text-xs text-slate-500 mt-1">
              * 현금/예금은 입력한 금액이 그대로 평가금액으로 사용됩니다.
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className={ui.label}>수량</label>
                <input
                  type="number"
                  required
                  min="0"
                  step="any"
                  className={ui.input}
                  placeholder="0"
                  value={formData.amount || ''}
                  onChange={(e) => handleChange('amount', e.target.value)}
                />
              </div>
              <div>
                <label className={ui.label}>현재 단가 (KRW)</label>
                <input
                  type="number"
                  required
                  min="0"
                  step="any"
                  className={ui.input}
                  placeholder="0"
                  value={formData.currentPrice || ''}
                  onChange={(e) => handleChange('currentPrice', e.target.value)}
                />
              </div>
            </div>

            <div>
              <label className={ui.label}>매수 평균가 (선택)</label>
              <input
                type="number"
                min="0"
                step="any"
                className={ui.input}
                placeholder="입력 시 수익률이 계산됩니다."
                value={formData.purchasePrice || ''}
                onChange={(e) => handleChange('purchasePrice', e.target.value)}
              />
              <p className="text-xs text-slate-500 mt-1">
                * 입력하지 않으면 현재가와 동일하게 설정됩니다.
              </p>
            </div>
          </>
        )}

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
