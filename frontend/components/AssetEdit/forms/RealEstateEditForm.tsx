
import React from 'react';
import { Edit3 } from 'lucide-react';

interface RealEstateEditFormProps {
    inputValue: string;
    setInputValue: (v: string) => void;
    onSave: () => void;
}

export const RealEstateEditForm: React.FC<RealEstateEditFormProps> = ({
    inputValue,
    setInputValue,
    onSave,
}) => {
    return (
        <div className="space-y-3">
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
                        if (e.key === 'Enter') onSave();
                    }}
                />
                <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                    <Edit3 size={18} />
                </div>
            </div>

            <p className="text-xs text-slate-400">
                주변 매물 시세를 참고하여 현재 예상 가치를 입력하세요.
            </p>
        </div>
    );
};
