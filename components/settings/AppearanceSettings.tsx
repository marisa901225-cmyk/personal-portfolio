import React from 'react';
import { Palette } from 'lucide-react';
import { AppSettings } from '../../types';

interface AppearanceSettingsProps {
    settings: AppSettings;
    onSettingsChange: (next: AppSettings) => void;
}

export const AppearanceSettings: React.FC<AppearanceSettingsProps> = ({ settings, onSettingsChange }) => {
    return (
        <div className="pt-3 border-t border-slate-100">
            <div className="flex items-center space-x-2 mb-3">
                <div className="p-1.5 bg-violet-100 rounded-lg">
                    <Palette size={16} className="text-violet-600" />
                </div>
                <h3 className="text-sm font-semibold text-slate-800">외관 설정</h3>
            </div>

            {/* 배경 이미지 토글 */}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <p className="text-sm text-slate-700">배경 이미지 사용</p>
                    <p className="text-xs text-slate-400">활성화하면 카드에 글래스 효과가 적용됩니다</p>
                </div>
                <button
                    type="button"
                    onClick={() =>
                        onSettingsChange({
                            ...settings,
                            bgEnabled: !settings.bgEnabled,
                        })
                    }
                    className={`relative w-12 h-6 rounded-full transition-colors ${settings.bgEnabled ? 'bg-indigo-600' : 'bg-slate-300'
                        }`}
                >
                    <span
                        className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${settings.bgEnabled ? 'translate-x-6' : 'translate-x-0'
                            }`}
                    />
                </button>
            </div>

            {settings.bgEnabled && (
                <div className="space-y-4 pl-2 border-l-2 border-indigo-200 animate-fade-in">
                    {/* 배경 이미지 업로드 */}
                    <div>
                        <label className="block text-xs font-medium text-slate-600 mb-1">
                            배경 이미지 업로드
                        </label>
                        <div className="flex items-center gap-2">
                            <label className="flex-1 flex items-center justify-center px-4 py-3 rounded-lg border-2 border-dashed border-slate-300 hover:border-indigo-400 cursor-pointer transition-colors">
                                <input
                                    type="file"
                                    accept="image/*"
                                    className="hidden"
                                    onChange={(e) => {
                                        const file = e.target.files?.[0];
                                        if (file) {
                                            // 파일 크기 체크 (5MB 제한)
                                            if (file.size > 5 * 1024 * 1024) {
                                                alert('이미지 파일이 너무 큽니다. 5MB 이하의 파일을 선택해주세요.');
                                                return;
                                            }
                                            const reader = new FileReader();
                                            reader.onload = (event) => {
                                                const base64Data = event.target?.result as string;
                                                onSettingsChange({
                                                    ...settings,
                                                    bgImageData: base64Data,
                                                });
                                            };
                                            reader.readAsDataURL(file);
                                        }
                                        // input 초기화 (같은 파일 다시 선택 가능하도록)
                                        e.target.value = '';
                                    }}
                                />
                                <span className="text-xs text-slate-500">
                                    {settings.bgImageData ? '다른 이미지 선택' : '이미지 파일 선택'}
                                </span>
                            </label>
                            {settings.bgImageData && (
                                <button
                                    type="button"
                                    onClick={() =>
                                        onSettingsChange({
                                            ...settings,
                                            bgImageData: undefined,
                                        })
                                    }
                                    className="px-3 py-2 text-xs text-red-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                >
                                    삭제
                                </button>
                            )}
                        </div>
                        {/* 이미지 미리보기 */}
                        {settings.bgImageData && (
                            <div className="mt-3 rounded-lg overflow-hidden border border-slate-200">
                                <img
                                    src={settings.bgImageData}
                                    alt="배경 이미지 미리보기"
                                    className="w-full h-24 object-cover"
                                />
                            </div>
                        )}
                        <p className="text-[10px] text-slate-400 mt-2">
                            * 이미지는 브라우저 로컬스토리지에 저장됩니다. (최대 5MB)
                        </p>
                    </div>

                    {/* 카드 불투명도 */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-xs font-medium text-slate-600">
                                카드 불투명도
                            </label>
                            <span className="text-xs text-slate-500">{settings.cardOpacity ?? 85}%</span>
                        </div>
                        <input
                            type="range"
                            min={50}
                            max={100}
                            value={settings.cardOpacity ?? 85}
                            onChange={(e) =>
                                onSettingsChange({
                                    ...settings,
                                    cardOpacity: Number(e.target.value),
                                })
                            }
                            className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                        />
                    </div>

                    {/* 배경 흐림 강도 */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-xs font-medium text-slate-600">
                                배경 흐림 (blur)
                            </label>
                            <span className="text-xs text-slate-500">{settings.bgBlur ?? 8}px</span>
                        </div>
                        <input
                            type="range"
                            min={0}
                            max={20}
                            value={settings.bgBlur ?? 8}
                            onChange={(e) =>
                                onSettingsChange({
                                    ...settings,
                                    bgBlur: Number(e.target.value),
                                })
                            }
                            className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                        />
                    </div>
                </div>
            )}
        </div>
    );
};
