import React, { useState } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { Lock, Server, KeyRound } from 'lucide-react';
import { useSettings } from '../../hooks/SettingsContext';
import { Layout } from './Layout';

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
    MemoriesPage,
    AuthCallbackPage,
} from '../pages';

const App: React.FC = () => {
    const { settings, setSettings } = useSettings();
    const [authInput, setAuthInput] = useState('');
    const [isNaverLoggingIn, setIsNaverLoggingIn] = useState(false);
    const [showApiKeyInput, setShowApiKeyInput] = useState(false);

    // 현재 경로가 /auth/callback 인지 확인
    const isCallbackPage = window.location.pathname === '/auth/callback';

    // 쿠키 인증 또는 API 토큰이 없고, 콜백 페이지가 아닐 때만 모달 표시
    const [showAuthModal, setShowAuthModal] = useState(
        !settings.apiToken && !settings.cookieAuth && !isCallbackPage
    );

    const handleAuthSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (!authInput.trim()) return;
        setSettings(prev => ({ ...prev, apiToken: authInput.trim() }));
        setShowAuthModal(false);
        setAuthInput('');
    };

    const handleNaverLogin = async () => {
        if (!settings.serverUrl) {
            alert('먼저 설정에서 서버 URL을 입력해주세요.');
            return;
        }
        setIsNaverLoggingIn(true);
        try {
            const response = await fetch(`${settings.serverUrl}/api/auth/naver/login`);
            if (!response.ok) {
                throw new Error('Failed to get login URL');
            }
            const data = await response.json();
            window.location.href = data.auth_url;
        } catch (error) {
            console.error('Naver login error:', error);
            alert('네이버 로그인 URL을 가져오지 못했습니다.');
            setIsNaverLoggingIn(false);
        }
    };

    // 쿠키 인증 또는 API 토큰이 설정되면 모달 숨기기
    React.useEffect(() => {
        if (settings.apiToken || settings.cookieAuth) {
            setShowAuthModal(false);
        }
    }, [settings.apiToken, settings.cookieAuth]);

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

                        <div className="p-8">
                            <div className="space-y-6">
                                {/* 네이버 로그인 세션 - 가장 눈에 띄게 */}
                                <div className="space-y-4">
                                    <button
                                        type="button"
                                        onClick={handleNaverLogin}
                                        disabled={isNaverLoggingIn || !settings.serverUrl}
                                        className="w-full flex items-center justify-center gap-3 px-4 py-4 bg-[#03C75A] hover:bg-[#02B350] disabled:bg-slate-300 text-white rounded-2xl font-bold transition-all shadow-lg shadow-green-100 active:scale-[0.98]"
                                    >
                                        <div className="w-6 h-6 bg-white rounded-full flex items-center justify-center text-[#03C75A] font-black text-sm">N</div>
                                        <span>{isNaverLoggingIn ? '로그인 처리 중...' : '네이버로 시작하기'}</span>
                                    </button>

                                    {!settings.serverUrl && (
                                        <div className="bg-amber-50 border border-amber-100 rounded-xl p-3 text-center">
                                            <p className="text-[11px] text-amber-700 leading-tight">
                                                서버 URL 설정이 필요합니다.<br />
                                                <Link to="/settings" className="font-bold underline ml-1">설정 바로가기</Link>
                                            </p>
                                        </div>
                                    )}
                                </div>

                                <div className="relative py-2">
                                    <div className="absolute inset-0 flex items-center px-2">
                                        <div className="w-full border-t border-slate-100"></div>
                                    </div>
                                    <div className="relative flex justify-center text-[11px] uppercase tracking-tighter">
                                        <span className="bg-white px-4 text-slate-300 font-medium">또는</span>
                                    </div>
                                </div>

                                {/* API 키 입력 섹션 - 체크박스로 제어 */}
                                <div className="space-y-4">
                                    <label className="flex items-center gap-3 px-1 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            className="w-5 h-5 rounded-lg border-2 border-slate-200 text-indigo-600 focus:ring-indigo-500 transition-all cursor-pointer"
                                            checked={showApiKeyInput}
                                            onChange={(e) => setShowApiKeyInput(e.target.checked)}
                                        />
                                        <span className="text-sm font-semibold text-slate-500 group-hover:text-slate-700 transition-colors">
                                            비상용 API 비밀번호 사용하기
                                        </span>
                                    </label>

                                    {showApiKeyInput && (
                                        <form onSubmit={handleAuthSubmit} className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                                            <div className="relative group">
                                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-300 group-focus-within:text-indigo-400 transition-colors">
                                                    <KeyRound size={18} />
                                                </div>
                                                <input
                                                    type="password"
                                                    autoFocus
                                                    className="w-full bg-slate-50 border-2 border-slate-100 rounded-2xl py-3.5 pl-11 pr-5 text-base font-medium transition-all focus:border-indigo-500 focus:bg-white focus:outline-none"
                                                    placeholder="API_TOKEN 입력"
                                                    value={authInput}
                                                    onChange={(e) => setAuthInput(e.target.value)}
                                                />
                                            </div>
                                            <button
                                                type="submit"
                                                className="w-full bg-slate-800 hover:bg-slate-900 text-white font-bold py-3.5 rounded-2xl shadow-xl shadow-slate-100 transition-all active:scale-[0.98]"
                                            >
                                                비밀번호로 입장
                                            </button>
                                        </form>
                                    )}
                                </div>

                                <div className="pt-2 text-center">
                                    <Link
                                        to="/settings"
                                        className="text-[11px] font-bold text-slate-400 hover:text-indigo-600 transition-colors"
                                    >
                                        서버 연결 설정이 필요하신가요?
                                    </Link>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* 서버 URL 또는 인증 토큰 누락 시 경고 */}
            {!settings.serverUrl || (!settings.apiToken && !settings.cookieAuth) ? (
                <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 w-[calc(100%-2rem)] max-w-md">
                    <div className="bg-white/90 backdrop-blur-md border border-amber-200 p-4 rounded-2xl shadow-2xl flex items-center gap-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
                        <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center flex-shrink-0">
                            <Server className="text-amber-600" size={24} />
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-bold text-slate-800">서버 연결이 필요합니다</p>
                            <p className="text-xs text-slate-500 truncate">네이버 로그인 또는 API 토큰 입력이 필요합니다.</p>
                        </div>
                        <Link
                            to="/settings"
                            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl transition-all shadow-lg shadow-indigo-200 active:scale-95"
                        >
                            설정으로
                        </Link>
                    </div>
                </div>
            ) : null}

            <Routes>
                {/* 네이버 로그인 콜백 (최상단 배치, Layout 및 AuthModal 영향 최소화) */}
                <Route path="/auth/callback" element={<AuthCallbackPage />} />

                <Route path="/" element={<Layout />}>
                    <Route index element={<Navigate to="/dashboard" replace />} />
                    <Route path="dashboard" element={<DashboardPage />} />
                    <Route path="assets" element={<AssetsPage />} />
                    <Route path="trades" element={<TradesPage />} />
                    <Route path="exchange" element={<ExchangePage />} />
                    <Route path="expenses" element={<ExpensesPage />} />
                    <Route path="ai-report" element={<AiReportPage />} />
                    <Route path="memories" element={<MemoriesPage />} />
                    <Route path="add-asset" element={<AddAssetPage />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Route>
            </Routes>
        </>
    );
};

export default App;
