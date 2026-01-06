import React from 'react';
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
} from 'lucide-react';

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

    return (
        <div className="min-h-screen flex flex-col md:flex-row bg-slate-50">
            {/* Sidebar (Desktop) */}
            <aside className="hidden md:flex flex-col w-64 border-r bg-white border-slate-200 h-screen sticky top-0">
                <div className="p-6 border-b border-slate-100">
                    <h1 className="text-lg font-bold text-indigo-600">MyAsset</h1>
                    <p className="text-xs text-slate-400 mt-1">Portfolio Manager</p>
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
                <header className="mb-6">
                    <h1 className="text-2xl md:text-3xl font-bold text-slate-900">
                        {getPageTitle(location.pathname)}
                    </h1>
                    <p className="text-sm text-slate-500 mt-1">
                        {getPageDescription(location.pathname)}
                    </p>
                </header>

                {/* 각 라우트의 컴포넌트가 여기에 렌더링됩니다 */}
                <Outlet />
            </main>
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
