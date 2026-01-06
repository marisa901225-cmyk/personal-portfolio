
import React from 'react';
import { Loader2, Sparkles } from 'lucide-react';

interface AiReportGeneratorProps {
    query: string;
    setQuery: (v: string) => void;
    maxTokens: number;
    setMaxTokens: (v: number) => void;
    handleGenerate: () => void;
    isLoading: boolean;
    isRemoteEnabled: boolean;
}

const MIN_TOKENS = 512;
const MAX_TOKENS_LIMIT = 10000;

export const AiReportGenerator: React.FC<AiReportGeneratorProps> = ({
    query,
    setQuery,
    maxTokens,
    setMaxTokens,
    handleGenerate,
    isLoading,
    isRemoteEnabled,
}) => {
    return (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">AI 리포트 생성</h2>
                    <p className="text-sm text-slate-500 mt-1">
                        백엔드에서 AI가 리포트를 생성하고, 자동으로 저장됩니다.
                    </p>
                </div>
                <div className="flex flex-col md:flex-row md:items-center gap-3">
                    <div className="flex-1 min-w-[220px]">
                        <label className="text-xs text-slate-500" htmlFor="ai-report-query">
                            요청 문장
                        </label>
                        <input
                            id="ai-report-query"
                            type="text"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="예: 2025년 6월 리포트, 2025년 2분기 리포트, 올해 연간 리포트"
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <label className="text-xs text-slate-500" htmlFor="ai-report-tokens">
                            토큰
                        </label>
                        <input
                            id="ai-report-tokens"
                            type="number"
                            min={MIN_TOKENS}
                            max={MAX_TOKENS_LIMIT}
                            value={maxTokens}
                            onChange={(event) => {
                                const value = Number(event.target.value);
                                if (!Number.isFinite(value)) return;
                                const clamped = Math.min(Math.max(value, MIN_TOKENS), MAX_TOKENS_LIMIT);
                                setMaxTokens(clamped);
                            }}
                            className="w-24 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={handleGenerate}
                        disabled={!isRemoteEnabled || isLoading}
                        className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors ${!isRemoteEnabled || isLoading
                            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                            : 'bg-indigo-600 text-white hover:bg-indigo-700'
                            }`}
                    >
                        {isLoading ? (
                            <>
                                <Loader2 size={16} className="animate-spin" />
                                생성 중...
                            </>
                        ) : (
                            <>
                                <Sparkles size={16} />
                                리포트 생성
                            </>
                        )}
                    </button>
                </div>
            </div>
            {!isRemoteEnabled && (
                <div className="mt-4 text-sm text-slate-500">
                    서버 URL과 API 비밀번호를 먼저 설정해주세요.
                </div>
            )}
            <div className="mt-4 text-xs text-slate-500">
                연간 요청은 GPT-5.2 Pro, 월/분기/반기는 GPT-5.2를 사용합니다.
            </div>
        </div>
    );
};
