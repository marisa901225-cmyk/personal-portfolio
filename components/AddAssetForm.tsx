import React, { useState } from 'react';
import { Asset, AssetCategory } from '../types';
import { X } from 'lucide-react';

interface AddAssetFormProps {
  onSave: (asset: Asset) => void;
  onCancel: () => void;
}

export const AddAssetForm: React.FC<AddAssetFormProps> = ({ onSave, onCancel }) => {
  const [formData, setFormData] = useState<Partial<Asset>>({
    name: '',
    ticker: '',
    category: AssetCategory.STOCK_KR,
    amount: 0,
    currentPrice: 0,
    purchasePrice: 0,
    currency: 'KRW'
  });

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
      currency: 'KRW'
    };
    onSave(newAsset);
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
            <label className="block text-sm font-medium text-slate-700 mb-2">티커/종목코드 (선택)</label>
            <input
                type="text"
                className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors uppercase"
                placeholder="예: 005930.KS, AAPL"
                value={formData.ticker || ''}
                onChange={(e) => handleChange('ticker', e.target.value)}
            />
            <p className="text-[10px] text-slate-400 mt-1">홈서버 연동 시 사용됩니다 (Yahoo Finance 기준)</p>
            </div>
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