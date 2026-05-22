import React, { useEffect, useMemo, useState } from 'react';
import { Bot, Clipboard, Eraser, FilePenLine, Send, Sparkles } from 'lucide-react';
import { ApiClient } from '@/shared/api/client';
import { useSettings } from '@hooks/useSettings';

const STORAGE_KEY = 'myasset.aiMemo.draft';

type MemoMode = 'memo' | 'ask' | 'rewrite';

const modeLabels: Record<MemoMode, string> = {
    memo: '정리',
    ask: '질문',
    rewrite: '다듬기',
};

export const AiMemoPage: React.FC = () => {
    const { settings } = useSettings();
    const [memo, setMemo] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '');
    const [instruction, setInstruction] = useState('');
    const [mode, setMode] = useState<MemoMode>('memo');
    const [answer, setAnswer] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const client = useMemo(
        () => new ApiClient(settings.serverUrl || '', settings.apiToken),
        [settings.apiToken, settings.serverUrl],
    );

    useEffect(() => {
        localStorage.setItem(STORAGE_KEY, memo);
    }, [memo]);

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        const trimmedInstruction = instruction.trim();
        if (!trimmedInstruction || !settings.serverUrl) return;

        setIsLoading(true);
        setError('');
        try {
            const response = await client.createAiChatMessage({
                memo,
                instruction: trimmedInstruction,
                max_tokens: 1536,
                temperature: mode === 'rewrite' ? 0.25 : 0.4,
                mode,
            });
            setAnswer(response.answer);
        } catch (err) {
            const message = err instanceof Error ? err.message : 'AI 서버 호출에 실패했습니다.';
            setError(message);
        } finally {
            setIsLoading(false);
        }
    };

    const appendAnswer = () => {
        if (!answer.trim()) return;
        setMemo((prev) => [prev.trim(), answer.trim()].filter(Boolean).join('\n\n'));
    };

    return (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
            <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                    <div className="flex items-center gap-2">
                        <FilePenLine size={18} className="text-indigo-600" />
                        <h2 className="text-sm font-semibold text-slate-900">메모</h2>
                    </div>
                    <button
                        type="button"
                        onClick={() => setMemo('')}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                        aria-label="메모 비우기"
                    >
                        <Eraser size={17} />
                    </button>
                </div>
                <textarea
                    value={memo}
                    onChange={(event) => setMemo(event.target.value)}
                    className="min-h-[520px] w-full resize-y rounded-b-2xl border-0 bg-white p-4 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-indigo-500"
                    placeholder="생각, 할 일, 초안, 링크, 정리할 문장을 적어두세요."
                />
            </section>

            <aside className="space-y-4">
                <form onSubmit={handleSubmit} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="mb-4 flex items-center gap-2">
                        <Bot size={18} className="text-indigo-600" />
                        <h2 className="text-sm font-semibold text-slate-900">AI 서버</h2>
                    </div>

                    <div className="mb-3 grid grid-cols-3 gap-2 rounded-xl bg-slate-100 p-1">
                        {(Object.keys(modeLabels) as MemoMode[]).map((key) => (
                            <button
                                key={key}
                                type="button"
                                onClick={() => setMode(key)}
                                className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${mode === key
                                    ? 'bg-white text-indigo-700 shadow-sm'
                                    : 'text-slate-500 hover:text-slate-800'
                                    }`}
                            >
                                {modeLabels[key]}
                            </button>
                        ))}
                    </div>

                    <textarea
                        value={instruction}
                        onChange={(event) => setInstruction(event.target.value)}
                        className="mb-3 min-h-28 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                        placeholder="예: 위 메모를 오늘 할 일 5개로 정리해줘."
                    />

                    {error && (
                        <div role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                            {error}
                        </div>
                    )}

                    {!settings.serverUrl && (
                        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
                            설정에서 서버 URL을 먼저 입력해야 합니다.
                        </div>
                    )}

                    <button
                        type="submit"
                        disabled={isLoading || !instruction.trim() || !settings.serverUrl}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                        {isLoading ? <Sparkles size={16} className="animate-pulse" /> : <Send size={16} />}
                        {isLoading ? '생각 중...' : 'AI에 보내기'}
                    </button>
                </form>

                <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                    <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                        <h2 className="text-sm font-semibold text-slate-900">응답</h2>
                        <button
                            type="button"
                            onClick={appendAnswer}
                            disabled={!answer.trim()}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label="응답을 메모에 붙이기"
                        >
                            <Clipboard size={17} />
                        </button>
                    </div>
                    <div className="min-h-64 whitespace-pre-wrap p-4 text-sm leading-6 text-slate-800">
                        {answer || <span className="text-slate-400">AI 응답이 여기에 표시됩니다.</span>}
                    </div>
                </section>
            </aside>
        </div>
    );
};

export default AiMemoPage;
