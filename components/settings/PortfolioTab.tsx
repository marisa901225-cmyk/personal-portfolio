import React from 'react';
import { Sliders } from 'lucide-react';
import { AppSettings, TargetIndexAllocation } from '../../lib/types';
import { AppearanceSettings } from './AppearanceSettings';

interface PortfolioTabProps {
    settings: AppSettings;
    onSettingsChange: (next: AppSettings) => void;
    onFetchFxRate: () => void;
    onApplyFxBaseFromHistory: () => void;
    onAllocationChange: (
        index: number,
        field: 'indexGroup' | 'targetWeight',
        value: string
    ) => void;
    onAddAllocationRow: () => void;
    onRemoveAllocationRow: (index: number) => void;
}

export const PortfolioTab: React.FC<PortfolioTabProps> = ({
    settings,
    onSettingsChange,
    onFetchFxRate,
    onApplyFxBaseFromHistory,
    onAllocationChange,
    onAddAllocationRow,
    onRemoveAllocationRow,
}) => (
    <div className="space-y-5 animate-fade-in">
        {/* 환율 설정 */}
        <div>
            <div className="flex items-center space-x-2 mb-3">
                <div className="p-1.5 bg-emerald-100 rounded-lg">
                    <Sliders size={16} className="text-emerald-600" />
                </div>
                <h3 className="text-sm font-semibold text-slate-800">환율 설정</h3>
            </div>
            <p className="text-xs text-slate-500 mb-3">
                USD 자산 기준으로, 기준 환율과 현재 환율을 입력하면 대시보드에서 추정 환차익/환차손을 보여줍니다.
            </p>
            <div className="flex items-center gap-2">
                <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        기준 USD/KRW
                    </label>
                    <input
                        type="number"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                        placeholder="예: 1300"
                        min={0}
                        value={settings.usdFxBase ?? ''}
                        onChange={(e) =>
                            onSettingsChange({
                                ...settings,
                                usdFxBase: e.target.value ? Number(e.target.value) || undefined : undefined,
                            })
                        }
                    />
                </div>
                <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        현재 USD/KRW
                    </label>
                    <input
                        type="number"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                        placeholder="예: 1350"
                        min={0}
                        value={settings.usdFxNow ?? ''}
                        onChange={(e) =>
                            onSettingsChange({
                                ...settings,
                                usdFxNow: e.target.value ? Number(e.target.value) || undefined : undefined,
                            })
                        }
                    />
                </div>
                <div className="flex flex-col gap-2">
                    <button
                        type="button"
                        onClick={onFetchFxRate}
                        className="px-3 py-2 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 whitespace-nowrap"
                    >
                        증권사에서 불러오기
                    </button>
                    <button
                        type="button"
                        onClick={onApplyFxBaseFromHistory}
                        className="px-3 py-2 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 whitespace-nowrap"
                    >
                        환전 평균 적용
                    </button>
                </div>
            </div>
        </div>

        {/* 목표 지수 비중 */}
        <div className="pt-3 border-t border-slate-100">
            <h3 className="text-sm font-semibold text-slate-800 mb-2">목표 지수 비중</h3>
            <p className="text-xs text-slate-500 mb-3">
                예: S&amp;P500 6 / NASDAQ100 3 / BOND+ETC 1 처럼 상대 비중을 입력하거나, 60 / 30 / 10 처럼 합계가 100이 되도록 입력하면
                자동으로 100% 기준으로 환산됩니다. (합계가 100이면 각 값을 %로 그대로 사용합니다.)
            </p>
            <div className="space-y-2">
                {(settings.targetIndexAllocations || []).map((alloc: TargetIndexAllocation, index: number) => (
                    <div key={index} className="flex items-center gap-2">
                        <input
                            type="text"
                            className="flex-1 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                            placeholder="지수 이름 (예: S&P500)"
                            value={alloc.indexGroup}
                            onChange={(e) => onAllocationChange(index, 'indexGroup', e.target.value)}
                        />
                        <input
                            type="number"
                            className="w-20 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                            placeholder="비율"
                            value={alloc.targetWeight || ''}
                            min={0}
                            step="any"
                            onChange={(e) => onAllocationChange(index, 'targetWeight', e.target.value)}
                        />
                        <button
                            type="button"
                            onClick={() => onRemoveAllocationRow(index)}
                            className="px-2 py-1 text-[11px] text-slate-400 hover:text-red-500"
                            disabled={(settings.targetIndexAllocations || []).length <= 1}
                        >
                            삭제
                        </button>
                    </div>
                ))}
            </div>
            <button
                type="button"
                onClick={onAddAllocationRow}
                className="mt-3 text-xs text-indigo-600 hover:text-indigo-700"
            >
                + 지수 비중 추가
            </button>
        </div>

        {/* 시장지수 비교 */}
        <div className="pt-3 border-t border-slate-100">
            <h3 className="text-sm font-semibold text-slate-800 mb-2">시장지수 비교</h3>
            <p className="text-xs text-slate-500 mb-3">
                자산 추이(1년) 수익률과 비교할 시장지수 수익률(%)을 입력하세요.
            </p>
            <div className="flex items-center gap-2">
                <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        지수 이름
                    </label>
                    <input
                        type="text"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                        placeholder="예: SPY TR"
                        value={settings.benchmarkName ?? ''}
                        onChange={(e) =>
                            onSettingsChange({
                                ...settings,
                                benchmarkName: e.target.value,
                            })
                        }
                    />
                </div>
                <div className="w-28">
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        수익률 (%)
                    </label>
                    <input
                        type="number"
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                        placeholder="예: 12.3"
                        step="any"
                        value={settings.benchmarkReturn ?? ''}
                        onChange={(e) => {
                            const raw = e.target.value;
                            const next = raw === '' ? undefined : Number(raw);
                            onSettingsChange({
                                ...settings,
                                benchmarkReturn: Number.isFinite(next) ? next : undefined,
                            });
                        }}
                    />
                </div>
            </div>
        </div>

        {/* 외관 설정 (분리된 컴포넌트 사용) */}
        <AppearanceSettings settings={settings} onSettingsChange={onSettingsChange} />
    </div>
);
