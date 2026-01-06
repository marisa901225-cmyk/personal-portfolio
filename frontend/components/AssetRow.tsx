import React, { useState } from 'react';
import { Asset, AssetCategory, TradeType } from '../lib/types';
import { formatCurrency } from '../lib/utils/constants';
import { Trash2, Edit3 } from 'lucide-react';

interface AssetRowProps {
    asset: Asset;
    onDelete: (id: string) => void;
    onTrade: (id: string, type: TradeType, quantity: number, price: number) => void;
    onEdit: (asset: Asset) => void;
    getDefaultFxRate: () => number;
}

export const AssetRow: React.FC<AssetRowProps> = ({
    asset,
    onDelete,
    onTrade,
    onEdit,
    getDefaultFxRate,
}) => {
    const [isTradeOpen, setIsTradeOpen] = useState(false);
    const [tradeType, setTradeType] = useState<TradeType>('BUY');
    const [tradeQuantity, setTradeQuantity] = useState<string>('');
    const [tradePrice, setTradePrice] = useState<string>('');
    const [tradeFxRate, setTradeFxRate] = useState<string>('');
    const [tradeUsdPrice, setTradeUsdPrice] = useState<string>('');

    const totalValue = asset.amount * asset.currentPrice;
    const profitRate = asset.purchasePrice
        ? ((asset.currentPrice - asset.purchasePrice) / asset.purchasePrice) * 100
        : 0;
    const isProfitable = profitRate > 0;
    const isLoss = profitRate < 0;
    const realized = asset.realizedProfit || 0;

    const openTrade = (type: TradeType) => {
        setIsTradeOpen(true);
        setTradeType(type);
        setTradeQuantity('');

        if (asset.category === AssetCategory.STOCK_US) {
            setTradeFxRate('');
            setTradeUsdPrice('');
            setTradePrice('');
        } else {
            setTradePrice(asset.currentPrice.toString());
            setTradeFxRate('');
            setTradeUsdPrice('');
        }
    };

    const closeTrade = () => {
        setIsTradeOpen(false);
        setTradeQuantity('');
        setTradePrice('');
        setTradeFxRate('');
        setTradeUsdPrice('');
    };

    const submitTrade = () => {
        const qty = Number(tradeQuantity);

        let finalPrice: number;

        if (asset.category === AssetCategory.STOCK_US) {
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

    return (
        <React.Fragment>
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
                    <div>{formatCurrency(asset.purchasePrice || 0)}</div>
                    {asset.category === AssetCategory.STOCK_US && asset.purchasePrice && (
                        <div className="text-[10px] text-slate-400 mt-0.5">
                            ${(asset.purchasePrice / getDefaultFxRate()).toFixed(2)}
                        </div>
                    )}
                </td>
                <td className="p-4 text-right">
                    <div className="text-slate-800 font-medium">{formatCurrency(asset.currentPrice)}</div>
                    {asset.category === AssetCategory.STOCK_US && (
                        <div className="text-[10px] text-slate-400 mt-0.5">
                            ${(asset.currentPrice / getDefaultFxRate()).toFixed(2)}
                        </div>
                    )}
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
                            onClick={() => openTrade('BUY')}
                            className="px-2 py-1 rounded-lg text-[11px] font-medium bg-red-50 text-red-600 hover:bg-red-100"
                        >
                            매수
                        </button>
                        <button
                            type="button"
                            onClick={() => openTrade('SELL')}
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
                            onClick={() => onEdit(asset)}
                            className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-full transition-all"
                            title={
                                asset.category === AssetCategory.CASH
                                    ? '예비금 잔액 수정'
                                    : asset.category === AssetCategory.REAL_ESTATE
                                        ? '부동산 시세 수정'
                                        : '자산 정보 수정'
                            }
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
            {isTradeOpen && (
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
                                        onClick={submitTrade}
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
};
