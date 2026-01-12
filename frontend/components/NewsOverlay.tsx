import React, { useEffect, useRef } from 'react';
import { useNewsQuery } from '@/shared/api/queries';
import { ApiClient } from '@/shared/api/client';
import { X, ExternalLink, Globe, Calendar, Loader2 } from 'lucide-react';

interface NewsOverlayProps {
    query: string;
    ticker?: string | null;
    isOpen: boolean;
    onClose: () => void;
    apiClient: ApiClient;
}

export const NewsOverlay: React.FC<NewsOverlayProps> = ({ query, ticker, isOpen, onClose, apiClient }) => {
    const { data, isLoading, isError } = useNewsQuery(apiClient, query, { enabled: isOpen, ticker });
    const overlayRef = useRef<HTMLDivElement>(null);

    // ESC 키로 닫기
    useEffect(() => {
        const handleEsc = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [onClose]);

    // 바깥 클릭 시 닫기
    const handleBackdropClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) onClose();
    };

    if (!isOpen) return null;

    return (
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm transition-all animate-in fade-in duration-200"
            onClick={handleBackdropClick}
        >
            <div
                ref={overlayRef}
                className="w-full max-w-lg bg-white/80 backdrop-blur-xl border border-white/20 rounded-3xl shadow-2xl overflow-hidden flex flex-col animate-in zoom-in-95 duration-200"
                style={{ maxHeight: '80vh' }}
            >
                {/* Header */}
                <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-white/50">
                    <div>
                        <h3 className="text-xl font-bold text-slate-900 flex items-center gap-2">
                            <Globe className="w-5 h-5 text-indigo-500" />
                            {query} {ticker && <span className="text-sm font-mono text-slate-400">({ticker})</span>} 관련 뉴스
                        </h3>
                        <p className="text-sm text-slate-500 mt-0.5">최신 기사 및 시장 동향</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-slate-100 rounded-full transition-colors"
                    >
                        <X size={20} className="text-slate-400" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                    {isLoading ? (
                        <div className="py-20 flex flex-col items-center justify-center space-y-4">
                            <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                            <p className="text-slate-400 font-medium">실시간 뉴스 수집 중...</p>
                        </div>
                    ) : isError ? (
                        <div className="py-20 text-center">
                            <p className="text-red-500">뉴스를 불러오는데 실패했습니다.</p>
                        </div>
                    ) : data?.articles.length === 0 ? (
                        <div className="py-20 text-center">
                            <Globe className="w-12 h-12 text-slate-100 mx-auto mb-4" />
                            <p className="text-slate-400">관련 뉴스가 아직 없습니다.</p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {data?.articles.map((article) => (
                                <a
                                    key={article.id}
                                    href={article.url || '#'}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block p-4 rounded-2xl bg-white border border-slate-100 hover:border-indigo-200 hover:shadow-md transition-all group"
                                >
                                    <div className="flex justify-between items-start gap-3">
                                        <h4 className="font-semibold text-slate-800 leading-snug group-hover:text-indigo-600 transition-colors">
                                            {article.title}
                                        </h4>
                                        <ExternalLink size={14} className="text-slate-300 group-hover:text-indigo-400 flex-shrink-0 mt-1" />
                                    </div>
                                    <p className="text-sm text-slate-500 mt-2 line-clamp-2 leading-relaxed">
                                        {article.snippet}
                                    </p>
                                    <div className="flex items-center gap-4 mt-3 text-[11px] font-medium text-slate-400">
                                        <span className="flex items-center gap-1 bg-slate-50 px-2 py-0.5 rounded">
                                            {article.source_name || '알 수 없는 출처'}
                                        </span>
                                        {article.published_at && (
                                            <span className="flex items-center gap-1">
                                                <Calendar size={12} />
                                                {new Date(article.published_at).toLocaleDateString()}
                                            </span>
                                        )}
                                    </div>
                                </a>
                            ))}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-4 bg-slate-50/50 border-t border-slate-100 text-center">
                    <p className="text-xs text-slate-400">
                        데이터는 실시간 검색 결과를 기반으로 제공됩니다.
                    </p>
                </div>
            </div>
        </div>
    );
};
