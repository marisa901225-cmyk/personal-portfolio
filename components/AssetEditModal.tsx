import React, { useState, useEffect } from 'react';
import { X, Edit3, Wallet, Tag, Home } from 'lucide-react';
import { Asset, AssetCategory } from '../types';
import { formatCurrency } from '../constants';
import { calculateCmaBalance, CmaConfig } from '../cmaConfig';

interface AssetEditModalProps {
    isOpen: boolean;
    onClose: () => void;
    asset: Asset | null;
    onUpdateAsset: (id: string, updates: { ticker?: string; indexGroup?: string }) => void;
    onUpdateCash: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => void | Promise<void>;
    /** 설정에서 정의된 지수 그룹 목록 (드롭다운에 표시) */
    indexGroupOptions?: string[];
}

export const AssetEditModal: React.FC<AssetEditModalProps> = ({
    isOpen,
    onClose,
    asset,
    onUpdateAsset,
    onUpdateCash,
    indexGroupOptions,
}) => {
    const [indexGroup, setIndexGroup] = useState('');
    const [inputValue, setInputValue] = useState('');
    const [isCmaEnabled, setIsCmaEnabled] = useState(false);
    const [annualRate, setAnnualRate] = useState('');
    const [taxRate, setTaxRate] = useState('15.4');
    const [startDate, setStartDate] = useState('');

    const formatDate = (d: Date): string => {
        const year = d.getFullYear();
        const month = `${d.getMonth() + 1}`.padStart(2, '0');
        const day = `${d.getDate()}`.padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    useEffect(() => {
        if (isOpen && asset) {
            setIndexGroup(asset.indexGroup || '');
            if (asset.category === AssetCategory.CASH || asset.category === AssetCategory.REAL_ESTATE) {
                // 현금/부동산 자산: 현재 총액(평가금액)을 표시
                const currentTotal = asset.amount * asset.currentPrice;
                setInputValue(Math.round(currentTotal).toString());

                const cfg = asset.cmaConfig;
                if (cfg) {
                    setIsCmaEnabled(true);
                    setAnnualRate(cfg.annualRate.toString());
                    setTaxRate(cfg.taxRate.toString());
                    setStartDate(cfg.startDate);
                } else {
                    setIsCmaEnabled(false);
                    setAnnualRate('');
                    setTaxRate('15.4');
                    setStartDate(formatDate(new Date()));
                }
            } else {
                // 일반 자산: 티커 표시
                setInputValue(asset.ticker || '');
                setIsCmaEnabled(false);
                setAnnualRate('');
                setTaxRate('15.4');
                setStartDate('');
            }
        }
    }, [isOpen, asset]);

    if (!isOpen || !asset) return null;

    const isCash = asset.category === AssetCategory.CASH;
    const isRealEstate = asset.category === AssetCategory.REAL_ESTATE;

    let cmaPreview: number | null = null;
    if (isCash && isCmaEnabled) {
        const principal = Number(inputValue.replace(/,/g, '').trim() || '0');
        const rate = Number(annualRate || '0');
        const tax = Number(taxRate || '0');
        if (principal > 0 && rate > 0 && startDate) {
            const cfg: CmaConfig = {
                principal,
                annualRate: rate,
                taxRate: tax,
                startDate,
            };
            cmaPreview = calculateCmaBalance(cfg, new Date());
        }
    }

    const handleSave = () => {
        if (isCash || isRealEstate) {
            // 현금 또는 부동산: 시세 직접 입력
            const trimmed = inputValue.replace(/,/g, '').trim();
            const value = Number(trimmed);
            if (!Number.isFinite(value) || value < 0) {
                alert('올바른 금액을 입력해주세요.');
                return;
            }

            let nextCmaConfig: CmaConfig | null = null;

            // CMA 자동 이자 설정 저장/해제 (현금만 해당)
            if (isCash && isCmaEnabled && value > 0) {
                const rate = Number(annualRate || '0');
                const tax = Number(taxRate || '0');
                if (!Number.isFinite(rate) || rate <= 0) {
                    alert('연 이자율(%)을 올바르게 입력해주세요.');
                    return;
                }
                const start = startDate || formatDate(new Date());
                nextCmaConfig = {
                    principal: value,
                    annualRate: rate,
                    taxRate: Number.isFinite(tax) && tax >= 0 ? tax : 15.4,
                    startDate: start,
                };
            }

            // 현금/부동산 시세 업데이트
            onUpdateCash(asset.id, value, nextCmaConfig);
        } else {
            // 주식/펀드 등: 티커 및 지수 그룹 업데이트
            const trimmed = inputValue.trim();
            onUpdateAsset(asset.id, {
                ticker: trimmed || undefined,
                indexGroup: indexGroup !== (asset.indexGroup || '') ? indexGroup : undefined
            });
        }
        onClose();
    };

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4 animate-fade-in"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="relative bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 p-6 text-white overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
                    <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>

                    <div className="relative flex justify-between items-start">
                        <div className="flex items-center gap-3">
                            <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                                {isCash ? <Wallet size={24} /> : isRealEstate ? <Home size={24} /> : <Tag size={24} />}
                            </div>
                            <div>
                                <h3 className="text-xl font-bold">
                                    {isCash ? '잔액 수정' : isRealEstate ? '시세 수정' : '자산 정보 수정'}
                                </h3>
                                <p className="text-sm text-indigo-100 mt-0.5">{asset.name}</p>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                        >
                            <X size={20} />
                        </button>
                    </div>
                </div>

                <div className="p-6 space-y-6">
                    <div className="space-y-3">
                        {/* 부동산 자산: 현재 시세 편집 */}
                        {isRealEstate && (
                            <>
                                <label className="block text-sm font-semibold text-slate-700">
                                    현재 시세 (KRW)
                                </label>

                                <div className="relative">
                                    <input
                                        type="text"
                                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                                        placeholder="예: 500000000"
                                        value={inputValue}
                                        onChange={(e) => setInputValue(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleSave();
                                        }}
                                        autoFocus
                                    />
                                    <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                                        <Edit3 size={18} />
                                    </div>
                                </div>

                                <p className="text-xs text-slate-400">
                                    주변 매물 시세를 참고하여 현재 예상 가치를 입력하세요.
                                </p>
                            </>
                        )}

                        {/* 주식/펀드 등 일반 자산: 티커 및 지수그룹 편집 */}
                        {!isCash && !isRealEstate && (
                            <>
                                <label className="block text-sm font-semibold text-slate-700">
                                    종목 티커 (Ticker)
                                </label>

                                <div className="relative">
                                    <input
                                        type="text"
                                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                                        placeholder="예: 005930, NAS:AAPL"
                                        value={inputValue}
                                        onChange={(e) => setInputValue(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleSave();
                                        }}
                                        autoFocus
                                    />
                                    <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                                        <Edit3 size={18} />
                                    </div>
                                </div>

                                <div className="mt-4">
                                    <label className="block text-sm font-semibold text-slate-700 mb-2">
                                        지수 그룹 (Index Group)
                                    </label>
                                    <input
                                        type="text"
                                        list="indexGroupOptions"
                                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all bg-white"
                                        placeholder="예: S&P500, NASDAQ100"
                                        value={indexGroup}
                                        onChange={(e) => setIndexGroup(e.target.value)}
                                    />
                                    <datalist id="indexGroupOptions">
                                        {indexGroupOptions?.map((opt) => (
                                            <option key={opt} value={opt} />
                                        ))}
                                    </datalist>
                                    <p className="text-xs text-slate-400 mt-1">포트폴리오 비중 계산에 사용됩니다. 직접 입력하거나 선택하세요.</p>
                                </div>

                                <p className="text-xs text-slate-400">
                                    정확한 시세 조회를 위해 올바른 티커를 입력해주세요.
                                </p>
                            </>
                        )}

                        {/* 현금 자산: 잔액 편집 */}
                        {isCash && (
                            <>
                                <label className="block text-sm font-semibold text-slate-700">
                                    현재 잔액 (KRW)
                                </label>

                                <div className="relative">
                                    <input
                                        type="text"
                                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                                        placeholder="예: 1000000"
                                        value={inputValue}
                                        onChange={(e) => setInputValue(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') handleSave();
                                        }}
                                        autoFocus
                                    />
                                    <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                                        <Edit3 size={18} />
                                    </div>
                                </div>

                                <p className="text-xs text-slate-400">
                                    실제 계좌의 현재 잔액을 입력하면 자동으로 수량이 조정됩니다.
                                </p>
                                <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
                                    <div className="flex items-center justify-between">
                                        <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                                            <input
                                                type="checkbox"
                                                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                                                checked={isCmaEnabled}
                                                onChange={(e) => setIsCmaEnabled(e.target.checked)}
                                            />
                                            <span>발행어음 / CMA 이자 자동 반영</span>
                                        </label>
                                        <span className="text-[10px] text-slate-400">
                                            가격 동기화 시 세후 이자 반영
                                        </span>
                                    </div>

                                    {isCmaEnabled && (
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                                            <div>
                                                <label className="block mb-1 text-slate-600">
                                                    연 이자율 (세전, %)
                                                </label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="0.01"
                                                    className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                                    placeholder="예: 4.5"
                                                    value={annualRate}
                                                    onChange={(e) => setAnnualRate(e.target.value)}
                                                />
                                            </div>
                                            <div>
                                                <label className="block mb-1 text-slate-600">
                                                    이자소득세율 (%)
                                                </label>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="0.1"
                                                    className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                                    placeholder="기본 15.4"
                                                    value={taxRate}
                                                    onChange={(e) => setTaxRate(e.target.value)}
                                                />
                                            </div>
                                            <div>
                                                <label className="block mb-1 text-slate-600">
                                                    이자 계산 시작일
                                                </label>
                                                <input
                                                    type="date"
                                                    className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                                    value={startDate}
                                                    onChange={(e) => setStartDate(e.target.value)}
                                                />
                                            </div>
                                        </div>
                                    )}

                                    {isCmaEnabled && cmaPreview !== null && (
                                        <p className="text-[11px] text-emerald-600">
                                            오늘 기준 예상 잔액(세후): <span className="font-semibold">{formatCurrency(cmaPreview)}</span>
                                        </p>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 bg-slate-50 border-t border-slate-200 flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-5 py-2.5 text-slate-600 text-sm font-semibold hover:bg-slate-200 rounded-xl transition-all"
                    >
                        취소
                    </button>
                    <button
                        onClick={handleSave}
                        className="px-6 py-2.5 bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-sm font-semibold hover:shadow-lg hover:scale-105 rounded-xl transition-all duration-200"
                    >
                        저장하기
                    </button>
                </div>
            </div>
        </div>
    );
};

