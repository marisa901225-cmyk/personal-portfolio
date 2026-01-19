import React, { useState, useEffect } from 'react';
import {
    Search,
    Trash2,

    Brain,
    Calendar,
    AlertCircle,
    Tag,
    Star,
    Clock,
    RefreshCw
} from 'lucide-react';
import { usePortfolio } from '@hooks/usePortfolio';
import { useSettings } from '@hooks/useSettings';
import { MemoryResponse, MemoryCategory } from '@/shared/api/client/types';

const CATEGORIES: { value: MemoryCategory | 'all'; label: string }[] = [
    { value: 'all', label: '전체' },
    { value: 'profile', label: '프로필' },
    { value: 'preference', label: '취향' },
    { value: 'project', label: '프로젝트' },
    { value: 'fact', label: '사실' },
    { value: 'general', label: '일반' },
];

export const MemoriesPage: React.FC = () => {
    const { settings } = useSettings();
    const { apiClient } = usePortfolio(settings);
    const [memories, setMemories] = useState<MemoryResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedCategory, setSelectedCategory] = useState<MemoryCategory | 'all'>('all');
    const [error, setError] = useState<string | null>(null);

    const loadMemories = async () => {
        if (!apiClient) return;
        try {
            setLoading(true);
            setError(null);
            let data: MemoryResponse[];

            if (searchQuery.trim()) {
                data = await apiClient.searchMemories({
                    query: searchQuery,
                    category: selectedCategory === 'all' ? undefined : selectedCategory,
                });
            } else {
                data = await apiClient.fetchMemories({
                    category: selectedCategory === 'all' ? undefined : selectedCategory,
                });
            }
            setMemories(data);
        } catch (err: unknown) {
            setError('기억을 불러오지 못했어요. ' + (err instanceof Error ? err.message : String(err)));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!apiClient) return;
        const timer = setTimeout(() => {
            loadMemories();
        }, 300);
        return () => clearTimeout(timer);
    }, [apiClient, searchQuery, selectedCategory]);

    const handleDelete = async (id: number) => {
        if (!apiClient) return;
        if (!window.confirm('이 기억을 지울까요?')) return;
        try {
            await apiClient.deleteMemory(id);
            setMemories(prev => prev.filter(m => m.id !== id));
        } catch (err: unknown) {
            alert('삭제 실패: ' + (err instanceof Error ? err.message : String(err)));
        }
    };

    const formatDate = (dateStr: string) => {
        return new Date(dateStr).toLocaleDateString('ko-KR', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    };

    const getImportanceStars = (importance: number) => {
        return Array.from({ length: 5 }).map((_, i) => (
            <Star
                key={i}
                size={12}
                className={i < importance ? 'fill-yellow-400 text-yellow-400' : 'text-slate-200'}
            />
        ));
    };

    return (
        <div className="space-y-6">
            {/* Search & Filter Bar */}
            <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100">
                <div className="flex flex-col md:flex-row gap-4">
                    <div className="relative flex-1">
                        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                        <input
                            type="text"
                            placeholder="기억 내용을 검색해보세요..."
                            className="w-full pl-11 pr-4 py-3 bg-slate-50 border-none rounded-2xl text-sm focus:ring-2 focus:ring-indigo-500 transition-all"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                    <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
                        {CATEGORIES.map(({ value, label }) => (
                            <button
                                key={value}
                                onClick={() => setSelectedCategory(value)}
                                className={`px-4 py-3 rounded-2xl text-sm font-medium whitespace-nowrap transition-all ${selectedCategory === value
                                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100'
                                    : 'bg-slate-50 text-slate-500 hover:bg-slate-100'
                                    }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {error && (
                <div className="bg-red-50 border border-red-100 p-4 rounded-2xl flex items-center gap-3 text-red-600 text-sm">
                    <AlertCircle size={18} />
                    {error}
                </div>
            )}

            {/* Grid View */}
            {loading ? (
                <div className="flex flex-col items-center justify-center py-20 gap-4">
                    <RefreshCw size={32} className="animate-spin text-indigo-500" />
                    <p className="text-slate-400 text-sm">기억 조각들을 찾는 중...</p>
                </div>
            ) : memories.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 bg-white rounded-3xl border border-dashed border-slate-200 gap-4">
                    <Brain size={48} className="text-slate-200" />
                    <p className="text-slate-400 text-sm">찾으시는 기억이 아직 없네요.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {memories.map((memory) => (
                        <div
                            key={memory.id}
                            className="group bg-white rounded-3xl p-6 border border-slate-100 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-500/5 transition-all duration-300 relative overflow-hidden"
                        >
                            {/* Importance Indicator */}
                            <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500 opacity-0 group-hover:opacity-100 transition-opacity" />

                            <div className="flex justify-between items-start mb-4">
                                <div className="flex items-center gap-2">
                                    <span className="px-2.5 py-1 bg-indigo-50 text-indigo-600 text-[10px] font-bold rounded-lg uppercase tracking-wider">
                                        {memory.category}
                                    </span>
                                    <div className="flex gap-0.5">
                                        {getImportanceStars(memory.importance)}
                                    </div>
                                </div>
                                <button
                                    onClick={() => handleDelete(memory.id)}
                                    className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-xl transition-all opacity-0 group-hover:opacity-100"
                                >
                                    <Trash2 size={16} />
                                </button>
                            </div>

                            <p className="text-slate-800 text-sm leading-relaxed mb-4 whitespace-pre-wrap">
                                {memory.content}
                            </p>

                            <div className="flex flex-wrap items-center gap-y-2 gap-x-4 pt-4 border-t border-slate-50">
                                <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                                    <Calendar size={12} />
                                    <span>{formatDate(memory.created_at)}</span>
                                </div>
                                {memory.expires_at && (
                                    <div className="flex items-center gap-1.5 text-[11px] text-amber-500 font-medium bg-amber-50 px-2 py-0.5 rounded-full">
                                        <Clock size={12} />
                                        <span>만료: {formatDate(memory.expires_at)}</span>
                                    </div>
                                )}
                                {memory.key && (
                                    <div className="flex items-center gap-1.5 text-[11px] text-indigo-400">
                                        <Tag size={12} />
                                        <span>{memory.key}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
