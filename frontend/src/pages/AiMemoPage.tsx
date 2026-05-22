import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Bot,
    CheckCircle2,
    Clipboard,
    Eraser,
    Eye,
    FilePenLine,
    Loader2,
    PencilLine,
    Plus,
    Send,
    Sparkles,
    Trash2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ApiClient } from '@/shared/api/client';
import type { BackendAiMemo } from '@/shared/api/client/types';
import { useSettings } from '@hooks/useSettings';

type MemoMode = 'memo' | 'ask' | 'rewrite';
type MemoView = 'edit' | 'preview';

const DEFAULT_TITLE = '새 메모';
const SAVE_DELAY_MS = 650;

const modeLabels: Record<MemoMode, string> = {
    memo: '정리',
    ask: '질문',
    rewrite: '다듬기',
};

const formatMemoDate = (value: string): string =>
    new Intl.DateTimeFormat('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    }).format(new Date(value));

const MarkdownBlock: React.FC<{ content: string; emptyText: string }> = ({ content, emptyText }) => {
    if (!content.trim()) {
        return <span className="text-slate-400">{emptyText}</span>;
    }

    return (
        <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
                table: ({ children }) => (
                    <div className="my-2 overflow-x-auto rounded-xl border border-slate-200">
                        <table className="w-full border-collapse text-left text-sm">{children}</table>
                    </div>
                ),
                th: ({ children }) => (
                    <th className="border-b border-slate-200 bg-slate-50 px-3 py-2 font-semibold text-slate-700">
                        {children}
                    </th>
                ),
                td: ({ children }) => (
                    <td className="border-b border-slate-100 px-3 py-2 align-top text-slate-800 last:text-right">
                        {children}
                    </td>
                ),
                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
                ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
                code: ({ children }) => (
                    <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em] text-slate-900">{children}</code>
                ),
            }}
        >
            {content}
        </ReactMarkdown>
    );
};

export const AiMemoPage: React.FC = () => {
    const { settings } = useSettings();
    const [memos, setMemos] = useState<BackendAiMemo[]>([]);
    const [activeMemoId, setActiveMemoId] = useState<number | null>(null);
    const [title, setTitle] = useState(DEFAULT_TITLE);
    const [memo, setMemo] = useState('');
    const [memoView, setMemoView] = useState<MemoView>('preview');
    const [instruction, setInstruction] = useState('');
    const [mode, setMode] = useState<MemoMode>('memo');
    const [answer, setAnswer] = useState('');
    const [error, setError] = useState('');
    const [saveStatus, setSaveStatus] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingMemos, setIsLoadingMemos] = useState(false);
    const [isSavingMemo, setIsSavingMemo] = useState(false);
    const hydratingRef = useRef(false);
    const saveTimerRef = useRef<number | null>(null);

    const client = useMemo(
        () => new ApiClient(settings.serverUrl || '', settings.apiToken),
        [settings.apiToken, settings.serverUrl],
    );

    const activeMemo = useMemo(
        () => memos.find((item) => item.id === activeMemoId) ?? null,
        [activeMemoId, memos],
    );

    const loadMemos = useCallback(async () => {
        if (!settings.serverUrl) {
            setMemos([]);
            setActiveMemoId(null);
            return;
        }

        setIsLoadingMemos(true);
        setError('');
        try {
            const list = await client.fetchAiMemos();
            if (list.length > 0) {
                setMemos(list);
                setActiveMemoId((current) => current ?? list[0].id);
                return;
            }

            const created = await client.createAiMemo({ title: DEFAULT_TITLE, content: '' });
            setMemos([created]);
            setActiveMemoId(created.id);
        } catch (err) {
            const message = err instanceof Error ? err.message : '메모를 불러오지 못했습니다.';
            setError(message);
        } finally {
            setIsLoadingMemos(false);
        }
    }, [client, settings.serverUrl]);

    useEffect(() => {
        void loadMemos();
    }, [loadMemos]);

    useEffect(() => {
        hydratingRef.current = true;
        setTitle(activeMemo?.title ?? DEFAULT_TITLE);
        setMemo(activeMemo?.content ?? '');
        setMemoView(activeMemo?.content.trim() ? 'preview' : 'edit');
        const timer = window.setTimeout(() => {
            hydratingRef.current = false;
        }, 0);
        return () => window.clearTimeout(timer);
    }, [activeMemoId]);

    useEffect(() => {
        if (!settings.serverUrl || activeMemoId === null || hydratingRef.current) return;
        const original = memos.find((item) => item.id === activeMemoId);
        if (!original || (original.title === title && original.content === memo)) return;

        if (saveTimerRef.current) {
            window.clearTimeout(saveTimerRef.current);
        }

        saveTimerRef.current = window.setTimeout(async () => {
            setIsSavingMemo(true);
            setSaveStatus('');
            try {
                const updated = await client.updateAiMemo(activeMemoId, {
                    title: title.trim() || DEFAULT_TITLE,
                    content: memo,
                });
                setMemos((items) => items.map((item) => (item.id === updated.id ? updated : item)));
                setSaveStatus('저장됨');
            } catch (err) {
                const message = err instanceof Error ? err.message : '메모 저장에 실패했습니다.';
                setError(message);
            } finally {
                setIsSavingMemo(false);
            }
        }, SAVE_DELAY_MS);

        return () => {
            if (saveTimerRef.current) {
                window.clearTimeout(saveTimerRef.current);
            }
        };
    }, [activeMemoId, client, memo, memos, settings.serverUrl, title]);

    const createMemo = async () => {
        if (!settings.serverUrl) return;
        setError('');
        try {
            const created = await client.createAiMemo({ title: DEFAULT_TITLE, content: '' });
            setMemos((items) => [created, ...items]);
            setActiveMemoId(created.id);
            setMemoView('edit');
        } catch (err) {
            const message = err instanceof Error ? err.message : '새 메모를 만들지 못했습니다.';
            setError(message);
        }
    };

    const deleteMemo = async () => {
        if (!settings.serverUrl || activeMemoId === null) return;
        setError('');
        try {
            await client.deleteAiMemo(activeMemoId);
            const remaining = memos.filter((item) => item.id !== activeMemoId);
            if (remaining.length > 0) {
                setMemos(remaining);
                setActiveMemoId(remaining[0].id);
                return;
            }

            const created = await client.createAiMemo({ title: DEFAULT_TITLE, content: '' });
            setMemos([created]);
            setActiveMemoId(created.id);
            setMemoView('edit');
        } catch (err) {
            const message = err instanceof Error ? err.message : '메모 삭제에 실패했습니다.';
            setError(message);
        }
    };

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        const trimmedInstruction = instruction.trim();
        if (!trimmedInstruction || !settings.serverUrl) return;

        setIsLoading(true);
        setError('');
        setAnswer('');
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
        setMemoView('preview');
        setAnswer('');
    };

    const clearMemo = () => setMemo('');

    return (
        <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_minmax(280px,360px)] 2xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.85fr)]">
            <section className="grid min-h-[420px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm md:min-h-[calc(100dvh-180px)] lg:grid-cols-[240px_minmax(0,1fr)]">
                <div className="border-b border-slate-100 bg-slate-50 lg:border-b-0 lg:border-r">
                    <div className="flex items-center justify-between border-b border-slate-100 px-3 py-3">
                        <div className="flex items-center gap-2">
                            <FilePenLine size={18} className="text-indigo-600" />
                            <h2 className="text-sm font-semibold text-slate-900">메모</h2>
                        </div>
                        <button
                            type="button"
                            onClick={createMemo}
                            disabled={!settings.serverUrl}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-white hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label="새 메모"
                        >
                            <Plus size={17} />
                        </button>
                    </div>
                    <div className="max-h-44 overflow-y-auto p-2 md:max-h-56 lg:max-h-[calc(100dvh-240px)]">
                        {isLoadingMemos ? (
                            <div className="flex items-center gap-2 px-3 py-4 text-xs text-slate-500">
                                <Loader2 size={14} className="animate-spin" />
                                불러오는 중
                            </div>
                        ) : memos.length > 0 ? (
                            memos.map((item) => (
                                <button
                                    key={item.id}
                                    type="button"
                                    onClick={() => setActiveMemoId(item.id)}
                                    className={`mb-1 w-full rounded-lg px-3 py-2 text-left transition-colors ${item.id === activeMemoId
                                        ? 'bg-white text-slate-950 shadow-sm'
                                        : 'text-slate-500 hover:bg-white/70 hover:text-slate-800'
                                        }`}
                                >
                                    <span className="block truncate text-sm font-semibold">{item.title}</span>
                                    <span className="block truncate text-xs">{formatMemoDate(item.updated_at)}</span>
                                </button>
                            ))
                        ) : (
                            <div className="px-3 py-4 text-xs text-slate-400">저장된 메모가 없습니다.</div>
                        )}
                    </div>
                </div>

                <div className="flex min-h-[420px] flex-col md:min-h-[calc(100dvh-180px)]">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
                        <input
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-sm font-semibold text-slate-900 outline-none transition-colors focus:border-indigo-200 focus:bg-indigo-50/40"
                            aria-label="메모 제목"
                        />
                        <div className="flex items-center gap-1">
                            {isSavingMemo ? (
                                <span className="inline-flex items-center gap-1 px-2 text-xs text-slate-400">
                                    <Loader2 size={13} className="animate-spin" />
                                    저장 중
                                </span>
                            ) : saveStatus ? (
                                <span className="inline-flex items-center gap-1 px-2 text-xs text-emerald-600">
                                    <CheckCircle2 size={13} />
                                    {saveStatus}
                                </span>
                            ) : null}
                            <button
                                type="button"
                                onClick={() => setMemoView(memoView === 'edit' ? 'preview' : 'edit')}
                                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
                                aria-label={memoView === 'edit' ? '마크다운 미리보기' : '편집'}
                            >
                                {memoView === 'edit' ? <Eye size={17} /> : <PencilLine size={17} />}
                            </button>
                            <button
                                type="button"
                                onClick={clearMemo}
                                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                                aria-label="메모 비우기"
                            >
                                <Eraser size={17} />
                            </button>
                            <button
                                type="button"
                                onClick={deleteMemo}
                                disabled={activeMemoId === null}
                                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label="메모 삭제"
                            >
                                <Trash2 size={17} />
                            </button>
                        </div>
                    </div>
                    {memoView === 'edit' ? (
                        <textarea
                            value={memo}
                            onChange={(event) => setMemo(event.target.value)}
                            className="min-h-[320px] flex-1 resize-y border-0 bg-white p-4 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-indigo-500 md:min-h-[calc(100dvh-260px)]"
                            placeholder="생각, 할 일, 초안, 링크, 정리할 문장을 적어두세요."
                        />
                    ) : (
                        <div className="min-h-[320px] flex-1 overflow-y-auto p-4 text-sm leading-6 text-slate-800 md:min-h-[calc(100dvh-260px)]">
                            <MarkdownBlock content={memo} emptyText="미리볼 마크다운 메모가 없습니다." />
                        </div>
                    )}
                </div>
            </section>

            <aside className="order-first space-y-4 md:order-none md:sticky md:top-4">
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
                    <div className="min-h-64 p-4 text-sm leading-6 text-slate-800">
                        <MarkdownBlock content={answer} emptyText="AI 응답이 여기에 표시됩니다." />
                    </div>
                </section>
            </aside>
        </div>
    );
};

export default AiMemoPage;
