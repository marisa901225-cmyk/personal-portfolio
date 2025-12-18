import React, { useState, useEffect } from 'react';
import { X, TrendingUp, Sparkles } from 'lucide-react';
import { DividendEntry } from '../types';
import { formatCurrency } from '../constants';

interface DividendEditModalProps {
    isOpen: boolean;
    onClose: () => void;
    dividends: DividendEntry[];
    onSave: (dividends: DividendEntry[]) => void;
}

export const DividendEditModal: React.FC<DividendEditModalProps> = ({
    isOpen,
    onClose,
    dividends,
    onSave,
}) => {
    const [year, setYear] = useState<number>(new Date().getFullYear());
    const [amount, setAmount] = useState<string>('');
    const [localDividends, setLocalDividends] = useState<DividendEntry[]>([]);

    useEffect(() => {
        if (isOpen) {
            setLocalDividends([...dividends].sort((a, b) => b.year - a.year));
            setYear(new Date().getFullYear());
            setAmount('');
        }
    }, [isOpen, dividends]);

    if (!isOpen) return null;

    const handleAdd = () => {
        const numAmount = parseInt(amount.replace(/,/g, ''), 10);
        if (!year || isNaN(numAmount) || numAmount <= 0) {
            alert('연도와 금액을 올바르게 입력해주세요.');
            return;
        }

        const newEntry = { year, total: numAmount };
        const others = localDividends.filter((d) => d.year !== year);
        const updated = [...others, newEntry].sort((a, b) => b.year - a.year);

        setLocalDividends(updated);
        setAmount('');
    };

    const handleDelete = (targetYear: number) => {
        if (!confirm(`${targetYear}년 배당 기록을 삭제하시겠습니까?`)) return;
        const updated = localDividends.filter((d) => d.year !== targetYear);
        setLocalDividends(updated);
    };

    const handleSave = () => {
        onSave(localDividends);
        onClose();
    };

    const totalDividends = localDividends.reduce((sum, d) => sum + d.total, 0);

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4 animate-fade-in"
            onClick={onClose}
        >
            <div
                className="bg-white rounded-3xl shadow-2xl w-full max-w-lg overflow-hidden transform transition-all"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header with gradient */}
                <div className="relative bg-gradient-to-br from-emerald-500 via-emerald-600 to-teal-600 p-6 text-white overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
                    <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>

                    <div className="relative flex justify-between items-start">
                        <div className="flex items-center gap-3">
                            <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                                <TrendingUp size={24} />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold">배당금 관리</h3>
                                <p className="text-sm text-emerald-50 mt-0.5">연도별 배당 수익 기록</p>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                        >
                            <X size={20} />
                        </button>
                    </div>

                    {totalDividends > 0 && (
                        <div className="mt-4 pt-4 border-t border-white/20">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-emerald-50">누적 배당금</span>
                                <span className="text-2xl font-bold">+{formatCurrency(totalDividends)}</span>
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-6 space-y-6">
                    {/* 입력 폼 */}
                    <div className="space-y-3">
                        <div className="flex items-center gap-2">
                            <Sparkles size={16} className="text-emerald-600" />
                            <label className="text-sm font-semibold text-slate-700">
                                새 배당금 추가
                            </label>
                        </div>
                        <div className="flex gap-2">
                            <input
                                type="number"
                                className="w-28 px-4 py-3 rounded-xl border-2 border-slate-200 text-sm font-medium focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-all"
                                placeholder="연도"
                                value={year}
                                onChange={(e) => setYear(Number(e.target.value))}
                            />
                            <input
                                type="text"
                                className="flex-1 px-4 py-3 rounded-xl border-2 border-slate-200 text-sm focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-all"
                                placeholder="금액 (원)"
                                value={amount}
                                onChange={(e) => setAmount(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') handleAdd();
                                }}
                            />
                            <button
                                onClick={handleAdd}
                                className="px-5 py-3 bg-gradient-to-r from-emerald-500 to-teal-600 text-white rounded-xl text-sm font-semibold hover:shadow-lg hover:scale-105 transition-all duration-200"
                            >
                                추가
                            </button>
                        </div>
                        <p className="text-xs text-slate-400 flex items-center gap-1">
                            <span className="w-1 h-1 bg-slate-400 rounded-full"></span>
                            이미 존재하는 연도를 입력하면 금액이 업데이트됩니다
                        </p>
                    </div>

                    {/* 목록 */}
                    <div className="space-y-3">
                        <label className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                            등록된 배당 내역
                            {localDividends.length > 0 && (
                                <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs font-bold rounded-full">
                                    {localDividends.length}건
                                </span>
                            )}
                        </label>
                        <div className="bg-gradient-to-br from-slate-50 to-slate-100/50 rounded-2xl p-4 max-h-64 overflow-y-auto space-y-2 border border-slate-200/50">
                            {localDividends.length === 0 ? (
                                <div className="text-center py-8">
                                    <div className="w-16 h-16 bg-slate-200 rounded-full mx-auto mb-3 flex items-center justify-center">
                                        <TrendingUp size={28} className="text-slate-400" />
                                    </div>
                                    <p className="text-sm text-slate-400 font-medium">등록된 배당금이 없습니다</p>
                                    <p className="text-xs text-slate-400 mt-1">위에서 배당금을 추가해보세요</p>
                                </div>
                            ) : (
                                localDividends.map((d, idx) => (
                                    <div
                                        key={d.year}
                                        className="group flex justify-between items-center bg-white px-4 py-3.5 rounded-xl border border-slate-200 shadow-sm hover:shadow-md hover:border-emerald-300 transition-all duration-200"
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 bg-gradient-to-br from-emerald-100 to-teal-100 rounded-lg flex items-center justify-center">
                                                <span className="text-sm font-bold text-emerald-700">{d.year.toString().slice(-2)}</span>
                                            </div>
                                            <div>
                                                <span className="text-sm font-semibold text-slate-700 block">{d.year}년</span>
                                                <span className="text-xs text-slate-400">배당 수익</span>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-3">
                                            <span className="text-base font-bold text-emerald-600">
                                                +{formatCurrency(d.total)}
                                            </span>
                                            <button
                                                onClick={() => handleDelete(d.year)}
                                                className="p-1.5 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all opacity-0 group-hover:opacity-100"
                                            >
                                                <X size={16} />
                                            </button>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
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
                        className="px-6 py-2.5 bg-gradient-to-r from-emerald-500 to-teal-600 text-white text-sm font-semibold hover:shadow-lg hover:scale-105 rounded-xl transition-all duration-200"
                    >
                        저장하기
                    </button>
                </div>
            </div>
        </div>
    );
};
