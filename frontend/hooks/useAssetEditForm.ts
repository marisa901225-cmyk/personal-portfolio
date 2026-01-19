
import { useState, useEffect } from 'react';
import { Asset, AssetCategory } from '../lib/types';
import { CmaConfig, calculateCmaBalance } from '@/shared/portfolio';

interface UseAssetEditFormProps {
    asset: Asset | null;
    isOpen: boolean;
    onUpdateAsset: (id: string, updates: Partial<Asset>) => void | Promise<void>;
    onUpdateCash: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => void | Promise<void>;
    onClose: () => void;
}

export const useAssetEditForm = ({
    asset,
    isOpen,
    onUpdateAsset,
    onUpdateCash,
    onClose,
}: UseAssetEditFormProps) => {
    const [indexGroup, setIndexGroup] = useState('');
    const [inputValue, setInputValue] = useState('');
    const [assetName, setAssetName] = useState('');
    const [amountInput, setAmountInput] = useState('');
    const [purchasePriceInput, setPurchasePriceInput] = useState('');
    const [currentPriceInput, setCurrentPriceInput] = useState('');
    const [category, setCategory] = useState<AssetCategory>(AssetCategory.STOCK_KR);
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
            setAssetName(asset.name);
            if (asset.category === AssetCategory.CASH || asset.category === AssetCategory.REAL_ESTATE) {
                const currentTotal = asset.amount * asset.currentPrice;
                setInputValue(Math.round(currentTotal).toString());
                setAmountInput('');
                setPurchasePriceInput('');
                setCurrentPriceInput('');

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
                setInputValue(asset.ticker || '');
                setAmountInput(asset.amount.toString());
                setPurchasePriceInput(asset.purchasePrice != null ? asset.purchasePrice.toString() : '');
                setCurrentPriceInput(asset.currentPrice > 0 ? asset.currentPrice.toString() : '');
                setCategory(asset.category);
                setIsCmaEnabled(false);
                setAnnualRate('');
                setTaxRate('15.4');
                setStartDate('');
            }
        }
    }, [isOpen, asset]);

    const cmaPreview = (() => {
        if (asset?.category === AssetCategory.CASH && isCmaEnabled) {
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
                return calculateCmaBalance(cfg, new Date());
            }
        }
        return null;
    })();

    const handleSave = async () => {
        if (!asset) return;
        const trimmedName = assetName.trim();
        if (!trimmedName) {
            alert('자산명을 입력해주세요.');
            return;
        }

        const nameChanged = trimmedName !== asset.name;
        const isCash = asset.category === AssetCategory.CASH;
        const isRealEstate = asset.category === AssetCategory.REAL_ESTATE;

        try {
            if (isCash || isRealEstate) {
                const trimmed = inputValue.replace(/,/g, '').trim();
                const value = Number(trimmed);
                if (!Number.isFinite(value) || value < 0) {
                    alert('올바른 금액을 입력해주세요.');
                    return;
                }

                let nextCmaConfig: CmaConfig | null = null;
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

                await onUpdateCash(asset.id, value, nextCmaConfig);
                if (nameChanged) {
                    await onUpdateAsset(asset.id, { name: trimmedName });
                }
            } else {
                const trimmed = inputValue.trim();
                const updates: Partial<Asset> = {};

                if (nameChanged) updates.name = trimmedName;
                if (trimmed !== (asset.ticker || '')) updates.ticker = trimmed || undefined;
                if (indexGroup !== (asset.indexGroup || '')) updates.indexGroup = indexGroup || undefined;
                if (category !== asset.category) updates.category = category;

                const amountTrimmed = amountInput.trim();
                if (!amountTrimmed) {
                    alert('보유 수량을 입력해주세요.');
                    return;
                }
                const amountValue = Number(amountTrimmed);
                if (!Number.isFinite(amountValue) || amountValue < 0) {
                    alert('보유 수량을 올바르게 입력해주세요.');
                    return;
                }
                if (amountValue !== asset.amount) updates.amount = amountValue;

                const purchaseTrimmed = purchasePriceInput.trim();
                if (purchaseTrimmed !== '') {
                    const purchaseValue = Number(purchaseTrimmed);
                    if (!Number.isFinite(purchaseValue) || purchaseValue < 0) {
                        alert('매수 평균가를 올바르게 입력해주세요.');
                        return;
                    }
                    if ((asset.purchasePrice ?? undefined) !== purchaseValue) {
                        updates.purchasePrice = purchaseValue;
                    }
                }

                if (category === AssetCategory.OTHER) {
                    const currentTrimmed = currentPriceInput.trim();
                    if (currentTrimmed === '') {
                        alert('현재 단가를 입력해주세요.');
                        return;
                    }
                    const currentValue = Number(currentTrimmed);
                    if (!Number.isFinite(currentValue) || currentValue < 0) {
                        alert('현재 단가를 올바르게 입력해주세요.');
                        return;
                    }
                    if (currentValue !== asset.currentPrice) {
                        updates.currentPrice = currentValue;
                    }
                }

                if (Object.keys(updates).length > 0) {
                    await onUpdateAsset(asset.id, updates);
                }
            }
            onClose();
        } catch (err: unknown) {
            console.error('Save asset failed:', err);
            alert('자산 저장 중 오류가 발생했습니다: ' + (err instanceof Error ? err.message : String(err)));
        }
    };

    return {
        state: {
            indexGroup,
            inputValue,
            assetName,
            amountInput,
            purchasePriceInput,
            currentPriceInput,
            category,
            isCmaEnabled,
            annualRate,
            taxRate,
            startDate,
            cmaPreview,
        },
        handlers: {
            setIndexGroup,
            setInputValue,
            setAssetName,
            setAmountInput,
            setPurchasePriceInput,
            setCurrentPriceInput,
            setCategory,
            setIsCmaEnabled,
            setAnnualRate,
            setTaxRate,
            setStartDate,
            handleSave,
        },
    };
};
