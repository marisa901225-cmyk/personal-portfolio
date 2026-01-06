import React, { useState, useEffect, useRef } from 'react';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import {
    LayoutDashboard,
    List,
    PlusCircle,
    Settings,
    ScrollText,
    ArrowLeftRight,
    Wallet,
    Sparkles,
    Bell,
    RefreshCw,
} from 'lucide-react';
import { usePortfolio } from '@hooks/usePortfolio';
import { useSettings } from '@hooks/useSettings';
import { formatCurrency } from '@lib/utils/constants';
import { NotificationModal } from '@components/NotificationModal';
import { InvestmentQuote } from '@components/InvestmentQuote';
import { TradeRecord } from '@lib/types';

const navItems = [
    { to: '/dashboard', icon: LayoutDashboard, label: '대시보드' },
    { to: '/assets', icon: List, label: '자산 목록' },
    { to: '/trades', icon: ScrollText, label: '거래 내역' },
    { to: '/exchange', icon: ArrowLeftRight, label: '환전 내역' },
    { to: '/expenses', icon: Wallet, label: '가계부' },
    { to: '/ai-report', icon: Sparkles, label: 'AI 리포트' },
    { to: '/add-asset', icon: PlusCircle, label: '자산 추가' },
];

export const Layout: React.FC = () => {
    const location = useLocation();
    const { settings } = useSettings();
    const {
        assets,
        tradeHistory,
        isSyncing,
        syncPrices,
        reload,
        apiClient
    } = usePortfolio(settings);

    const [isHistoryOpen, setIsHistoryOpen] = useState(false);
    const [hasUnreadHistory, setHasUnreadHistory] = useState(false);
    const [syncNotification, setSyncNotification] = useState({
        isOpen: false,
        title: '',
        message: '',
    });

    const prevTradeCountRef = useRef(tradeHistory.length);

    useEffect(() => {
        const prevCount = prevTradeCountRef.current;
        const currentCount = tradeHistory.length;
        prevTradeCountRef.current = currentCount;

        if (currentCount > prevCount && !isHistoryOpen) {
            setHasUnreadHistory(true);
        }
    }, [tradeHistory.length, isHistoryOpen]);

    const handleSyncPrices = async () => {
        if (!settings.serverUrl) {
            alert('설정에서 홈서버 URL을 입력해주세요.');
            return;
        }
        await syncPrices({
            createSnapshot: true,
            onSuccess: () => {
                setSyncNotification({
                    isOpen: true,
                    title: '동기화 완료',
                    message: '가격 동기화 및 서버 저장이 완료되었습니다.',
                });
            },
        });
    };

    // 배경 스타일 계산
    const bgStyle: React.CSSProperties = settings.bgEnabled && settings.bgImageData
        ? {
            backgroundImage: `url(${settings.bgImageData})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            backgroundAttachment: 'fixed',
        }
        : {};

    return (
        <div
            className={`min-h-screen flex flex-col md:flex-row ${!settings.bgEnabled ? 'bg-slate-50' : ''}`}
            style={bgStyle}
        >
            {/* Sidebar (Desktop) */}
            <aside
                className={`hidden md:flex flex-col w-64 border-r h-screen sticky top-0 ${settings.bgEnabled
                    ? 'bg-white/80 backdrop-blur-md border-white/20'
                    : 'bg-white border-slate-200'
                    }`}
                style={settings.bgEnabled ? { backdropFilter: `blur(${settings.bgBlur ?? 8}px)` } : {}}
            >
                <div className={`p-6 ${settings.bgEnabled ? 'border-b border-white/20' : 'border-b border-slate-100'}`}>
                    <InvestmentQuote />
                </div>

                <nav className="flex-1 p-4 space-y-2">
                    {navItems.map(({ to, icon: Icon, label }) => (
                        <NavLink
                            key={to}
                            to={to}
                            className={({ isActive }) =>
                                `flex items-center space-x-3 px-4 py-3 rounded-xl transition-all w-full ${isActive
                                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
                                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                                }`
                            }
                        >
                            <Icon size={20} />
                            <span className="font-medium">{label}</span>
                        </NavLink>
                    ))}
                </nav>

                <div className="p-4 border-t border-slate-100">
                    <NavLink
                        to="/settings"
                        className={({ isActive }) =>
                            `flex items-center space-x-3 px-4 py-3 w-full rounded-xl transition-colors ${isActive
                                ? 'bg-slate-100 text-slate-900'
                                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
                            }`
                        }
                    >
                        <Settings size={20} />
                        <span className="font-medium">설정</span>
                    </NavLink>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 p-4 md:p-8 max-w-6xl mx-auto w-full">
                <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl md:text-3xl font-bold text-slate-900">
                            {getPageTitle(location.pathname)}
                        </h1>
                        <p className="text-sm text-slate-500 mt-1">
                            {getPageDescription(location.pathname)}
                        </p>
                    </div>

                    <div className="flex items-center gap-3">
                        <button
                            type="button"
                            onClick={() => {
                                const next = !isHistoryOpen;
                                setIsHistoryOpen(next);
                                if (next) setHasUnreadHistory(false);
                            }}
                            className="relative p-2 rounded-full border border-slate-200 bg-white text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
                        >
                            <Bell size={20} />
                            {hasUnreadHistory && (
                                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-red-500 rounded-full" />
                            )}
                        </button>
                        <button
                            type="button"
                            onClick={handleSyncPrices}
                            disabled={isSyncing}
                            className="inline-flex items-center px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium shadow-sm hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed"
                        >
                            <RefreshCw
                                size={16}
                                className={`mr-2 ${isSyncing ? 'animate-spin' : ''}`}
                            />
                            {isSyncing ? '동기화 중...' : '가격 동기화'}
                        </button>
                    </div>
                </header>

                {/* 최근 거래 내역 패널 */}
                {isHistoryOpen && (
                    <section className="mb-4 animate-fade-in-up">
                        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                            <div className="flex items-center justify-between mb-3">
                                <h2 className="text-sm font-semibold text-slate-800">최근 거래 내역</h2>
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={() => setIsHistoryOpen(false)}
                                        className="text-xs text-slate-400 hover:text-slate-600"
                                    >
                                        닫기
                                    </button>
                                </div>
                            </div>
                            {tradeHistory.length === 0 ? (
                                <p className="text-xs text-slate-400">아직 기록된 거래가 없습니다.</p>
                            ) : (
                                <ul className="divide-y divide-slate-100 text-xs max-h-60 overflow-y-auto">
                                    {tradeHistory.slice(0, 10).map((trade: TradeRecord) => {
                                        const isBuy = trade.type === 'BUY';
                                        const ts = new Date(trade.timestamp);
                                        const labelTime = ts.toLocaleString('ko-KR', {
                                            month: '2-digit',
                                            day: '2-digit',
                                            hour: '2-digit',
                                            minute: '2-digit',
                                        });
                                        const pnl = trade.realizedDelta ?? 0;
                                        return (
                                            <li key={trade.id} className="py-2 flex items-center justify-between gap-3">
                                                <div className="flex-1">
                                                    <div className="flex items-center gap-2">
                                                        <span
                                                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${isBuy ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600'
                                                                }`}
                                                        >
                                                            {isBuy ? '매수' : '매도'}
                                                        </span>
                                                        <span className="text-[11px] text-slate-500">{labelTime}</span>
                                                    </div>
                                                    <div className="mt-0.5 text-[13px] text-slate-800">
                                                        {trade.assetName}
                                                        {trade.ticker && (
                                                            <span className="ml-1 text-[10px] text-slate-500">
                                                                ({trade.ticker})
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="mt-0.5 text-[11px] text-slate-500">
                                                        {trade.quantity.toLocaleString()}개 @ {formatCurrency(trade.price)}
                                                    </div>
                                                </div>
                                                {!isBuy && (
                                                    <div
                                                        className={`text-right text-[11px] font-semibold ${pnl > 0
                                                            ? 'text-red-500'
                                                            : pnl < 0
                                                                ? 'text-blue-500'
                                                                : 'text-slate-400'
                                                            }`}
                                                    >
                                                        {pnl > 0 ? '+' : pnl < 0 ? '-' : ''}
                                                        {formatCurrency(Math.abs(pnl))}
                                                    </div>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            )}
                        </div>
                    </section>
                )}

                {/* 각 라우트의 컴포넌트가 여기에 렌더링됩니다 */}
                <Outlet />
            </main>

            <NotificationModal
                isOpen={syncNotification.isOpen}
                onClose={() => setSyncNotification((prev) => ({ ...prev, isOpen: false }))}
                title={syncNotification.title}
                message={syncNotification.message}
            />
        </div>
    );
};

function getPageTitle(pathname: string): string {
    const titles: Record<string, string> = {
        '/dashboard': '대시보드',
        '/assets': '보유 자산',
        '/trades': '거래 내역',
        '/exchange': '환전 내역',
        '/expenses': '가계부',
        '/ai-report': 'AI 리포트',
        '/add-asset': '자산 추가',
        '/settings': '서버 설정',
    };
    return titles[pathname] || '대시보드';
}

function getPageDescription(pathname: string): string {
    const descriptions: Record<string, string> = {
        '/dashboard': '자산 현황 한눈에 보기',
        '/assets': '자산 관리 및 거래',
        '/trades': '전체 거래 기록 조회',
        '/exchange': '환전 기록 조회 및 수정',
        '/expenses': '월별 지출/수입 분석',
        '/ai-report': '가계부 + 투자 리포트 생성',
        '/add-asset': '새로운 자산 등록',
        '/settings': '연결 및 환경 설정',
    };
    return descriptions[pathname] || '자산 현황 한눈에 보기';
}
