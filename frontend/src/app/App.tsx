import React, { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Lock, KeyRound } from 'lucide-react';
import { Layout } from './Layout';
import { useSettings } from '@hooks/useSettings';

// 실제 페이지 컴포넌트들
import {
    DashboardPage,
    AssetsPage,
    TradesPage,
    ExchangePage,
    ExpensesPage,
    AiReportPage,
    AddAssetPage,
    SettingsPage,
} from '@/pages';

const App: React.FC = () => {
    const { settings, setSettings } = useSettings();
    const [authInput, setAuthInput] = useState('');
    const [showAuthModal, setShowAuthModal] = useState(!settings.apiToken);

    const handleAuthSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!authInput.trim()) return;
        setSettings(prev => ({ ...prev, apiToken: authInput.trim() }));
        setShowAuthModal(false);
        setAuthInput('');
    };

    return (
        <>
            {showAuthModal && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4">
                    <div className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all">
                        <div className="relative bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 p-6 text-white overflow-hidden">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
                            <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>
                            <div className="relative flex items-center gap-3">
                                <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                                    <Lock size={24} />
                                </div>
                                <div>
                                    <h3 className="text-xl font-bold">포트폴리오 로그인</h3>
                                    <p className="text-sm text-indigo-100 mt-0.5">비밀번호를 입력하세요</p>
                                </div>
                            </div>
                        </div>

                        <form onSubmit={handleAuthSubmit} className="p-6 space-y-6">
                            <div className="space-y-3">
                                <label className="block text-sm font-semibold text-slate-700">API 비밀번호</label>
                                <div className="relative">
                                    <input
                                        type="password"
                                        autoFocus
                                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all font-mono"
                                        placeholder="비밀번호 입력"
                                        value={authInput}
                                        onChange={(e) => setAuthInput(e.target.value)}
                                    />
                                    <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                                        <KeyRound size={18} />
                                    </div>
                                </div>
                                <p className="text-xs text-slate-400 flex items-center gap-1">
                                    <span className="w-1 h-1 bg-slate-400 rounded-full"></span>
                                    백엔드 서버의 <code className="px-1 py-0.5 bg-slate-100 rounded text-slate-600">API_TOKEN</code> 값을 입력하세요
                                </p>
                            </div>
                            <button
                                type="submit"
                                className="w-full py-3 bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:scale-[1.02] transition-all duration-200"
                            >
                                포트폴리오 들어가기
                            </button>
                        </form>
                    </div>
                </div>
            )}

            <Routes>
                <Route path="/" element={<Layout />}>
                    <Route index element={<Navigate to="/dashboard" replace />} />
                    <Route path="dashboard" element={<DashboardPage />} />
                    <Route path="assets" element={<AssetsPage />} />
                    <Route path="trades" element={<TradesPage />} />
                    <Route path="exchange" element={<ExchangePage />} />
                    <Route path="expenses" element={<ExpensesPage />} />
                    <Route path="ai-report" element={<AiReportPage />} />
                    <Route path="add-asset" element={<AddAssetPage />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Route>
            </Routes>
        </>
    );
};

export default App;
