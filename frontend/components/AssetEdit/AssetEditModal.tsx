
import React from 'react';
import { Asset, AssetCategory } from '../../lib/types';
import { CmaConfig } from '../../lib/utils/cmaConfig';
import { useAssetEditForm } from '../../hooks/useAssetEditForm';
import { AssetEditHeader } from './AssetEditHeader';
import { CashEditForm } from './forms/CashEditForm';
import { RealEstateEditForm } from './forms/RealEstateEditForm';
import { StockEditForm } from './forms/StockEditForm';

export interface AssetEditModalProps {
    isOpen: boolean;
    onClose: () => void;
    asset: Asset | null;
    onUpdateAsset: (id: string, updates: any) => void;
    onUpdateCash: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => void | Promise<void>;
    indexGroupOptions?: string[];
}

export const AssetEditModal: React.FC<AssetEditModalProps> = (props) => {
    const { asset, isOpen, onClose } = props;
    const { state, handlers } = useAssetEditForm(props);

    if (!isOpen || !asset) return null;

    const isCash = asset.category === AssetCategory.CASH;
    const isRealEstate = asset.category === AssetCategory.REAL_ESTATE;

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4 animate-fade-in"
            onMouseDown={onClose}
        >
            <div
                className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all"
                onMouseDown={(e) => e.stopPropagation()}
            >
                <AssetEditHeader
                    isCash={isCash}
                    isRealEstate={isRealEstate}
                    assetName={state.assetName}
                    onClose={onClose}
                />

                <div className="p-6 space-y-6">
                    <div className="space-y-3">
                        <div>
                            <label className="block text-sm font-semibold text-slate-700">
                                자산명
                            </label>
                            <div className="relative">
                                <input
                                    type="text"
                                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                                    placeholder="예: 삼성전자"
                                    value={state.assetName}
                                    onChange={(e) => handlers.setAssetName(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') handlers.handleSave();
                                    }}
                                    autoFocus
                                />
                            </div>
                        </div>

                        {isRealEstate && (
                            <RealEstateEditForm
                                inputValue={state.inputValue}
                                setInputValue={handlers.setInputValue}
                                onSave={handlers.handleSave}
                            />
                        )}

                        {!isCash && !isRealEstate && (
                            <StockEditForm
                                inputValue={state.inputValue}
                                setInputValue={handlers.setInputValue}
                                amountInput={state.amountInput}
                                setAmountInput={handlers.setAmountInput}
                                purchasePriceInput={state.purchasePriceInput}
                                setPurchasePriceInput={handlers.setPurchasePriceInput}
                                category={state.category}
                                setCategory={handlers.setCategory}
                                indexGroup={state.indexGroup}
                                setIndexGroup={handlers.setIndexGroup}
                                indexGroupOptions={props.indexGroupOptions}
                                onSave={handlers.handleSave}
                            />
                        )}

                        {isCash && (
                            <CashEditForm
                                inputValue={state.inputValue}
                                setInputValue={handlers.setInputValue}
                                isCmaEnabled={state.isCmaEnabled}
                                setIsCmaEnabled={handlers.setIsCmaEnabled}
                                annualRate={state.annualRate}
                                setAnnualRate={handlers.setAnnualRate}
                                taxRate={state.taxRate}
                                setTaxRate={handlers.setTaxRate}
                                startDate={state.startDate}
                                setStartDate={handlers.setStartDate}
                                cmaPreview={state.cmaPreview}
                                onSave={handlers.handleSave}
                            />
                        )}
                    </div>
                </div>

                <div className="p-6 bg-slate-50 border-t border-slate-200 flex justify-end gap-3">
                    <button
                        onClick={onClose}
                        className="px-5 py-2.5 text-slate-600 text-sm font-semibold hover:bg-slate-200 rounded-xl transition-all"
                    >
                        취소
                    </button>
                    <button
                        onClick={handlers.handleSave}
                        className="px-6 py-2.5 bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-sm font-semibold hover:shadow-lg hover:scale-105 rounded-xl transition-all duration-200"
                    >
                        저장하기
                    </button>
                </div>
            </div>
        </div>
    );
};
