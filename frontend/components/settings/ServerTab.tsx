import React, { useState } from 'react';
import { Server, LogIn, LogOut, User } from 'lucide-react';
import { AppSettings } from '../../lib/types';
import { cn, ui } from '@/shared/ui';

interface ServerTabProps {
    settings: AppSettings;
    onSettingsChange: (next: AppSettings) => void;
    onCheckHealth: () => void;
}

export const ServerTab: React.FC<ServerTabProps> = ({ settings, onSettingsChange, onCheckHealth }) => {
    const [isLoggingIn, setIsLoggingIn] = useState(false);

    const handleNaverLogin = async () => {
        setIsLoggingIn(true);
        try {
            // 백엔드에서 네이버 로그인 URL 가져오기
            const response = await fetch(`${settings.serverUrl}/api/auth/naver/login`, {
                credentials: 'include',
            });
            if (!response.ok) {
                throw new Error('Failed to get login URL');
            }
            const data = await response.json();

            // 네이버 로그인 페이지로 리다이렉트
            window.location.href = data.auth_url;
        } catch (error) {
            console.error('Naver login error:', error);
            alert('네이버 로그인 URL을 가져오지 못했습니다.');
            setIsLoggingIn(false);
        }
    };

    const handleLogout = async () => {
        if (settings.serverUrl) {
            try {
                await fetch(`${settings.serverUrl}/api/auth/naver/logout`, {
                    method: 'POST',
                    credentials: 'include',
                });
            } catch (error) {
                console.warn('Naver logout failed:', error);
            }
        }

        // 인증 상태 및 사용자 정보 제거
        onSettingsChange({
            ...settings,
            cookieAuth: false,
            naverUser: undefined,
        });
    };

    const isLoggedIn = !!(settings.cookieAuth && settings.naverUser);

    return (
        <div className="space-y-4 animate-fade-in">
            <div className="flex items-center space-x-3 mb-4 pb-4 border-b border-slate-100">
                <div className="p-2 bg-slate-100 rounded-lg">
                    <Server size={24} className="text-slate-600" />
                </div>
                <div>
                    <h2 className="text-lg font-bold text-slate-800">홈서버 연결 설정</h2>
                    <p className="text-sm text-slate-500">Tailscale을 통한 백엔드 연결</p>
                </div>
            </div>

            <div>
                <label className={ui.label}>홈서버 API URL</label>
                <input
                    type="text"
                    className={cn(ui.input, 'font-mono text-sm')}
                    placeholder="https://your-server.ts.net"
                    value={settings.serverUrl}
                    onChange={(e) =>
                        onSettingsChange({
                            ...settings,
                            serverUrl: e.target.value,
                        })
                    }
                />
                <p className="text-xs text-slate-500 mt-2">
                    * Vercel 배포 시 반드시 **https://** 주소를 사용해야 합니다.
                    <br />
                    * Tailscale HTTPS 기능을 켜고 **.ts.net** 주소를 사용하는 것이 좋습니다.
                </p>
                <button
                    type="button"
                    onClick={onCheckHealth}
                    className="mt-3 inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
                >
                    백엔드 서버 상태 확인
                </button>
            </div>

            {/* 네이버 로그인 섹션 */}
            <div className="border-t border-slate-200 pt-4">
                <label className={cn(ui.label, 'mb-3')}>네이버 로그인</label>

                {isLoggedIn ? (
                    <div className="bg-green-50 border border-green-200 rounded-xl p-4">
                        <div className="flex items-start justify-between">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-green-100 rounded-lg">
                                    <User size={20} className="text-green-600" />
                                </div>
                                <div>
                                    <p className="text-sm font-semibold text-green-800">
                                        {settings.naverUser?.nickname || settings.naverUser?.name || '사용자'}
                                    </p>
                                    <p className="text-xs text-green-600 mt-0.5">
                                        {settings.naverUser?.email || `ID: ${settings.naverUser?.id}`}
                                    </p>
                                    <p className="text-xs text-green-500 mt-1">✅ 로그인됨</p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={handleLogout}
                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-600 hover:text-red-700 hover:bg-red-100 rounded-lg transition-colors"
                            >
                                <LogOut size={14} />
                                로그아웃
                            </button>
                        </div>
                    </div>
                ) : (
                    <button
                        type="button"
                        onClick={handleNaverLogin}
                        disabled={isLoggingIn}
                        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-[#03C75A] hover:bg-[#02B350] disabled:bg-slate-300 text-white rounded-xl font-semibold transition-colors shadow-sm"
                    >
                        <LogIn size={18} />
                        {isLoggingIn ? '로그인 처리 중...' : '네이버로 로그인'}
                    </button>
                )}

                <p className="text-xs text-slate-500 mt-3">
                    * 네이버 로그인을 사용하면 안전하게 인증할 수 있습니다.
                    <br />
                    * 로그인 후 쿠키 기반 인증이 자동으로 적용됩니다.
                </p>
            </div>

            <div className="bg-blue-50 p-4 rounded-xl">
                <h4 className="font-semibold text-blue-800 text-sm mb-2">사용 팁</h4>
                <ul className="text-xs text-blue-700 space-y-1 list-disc list-inside">
                    <li>홈서버에 Python Backend가 실행 중이어야 합니다.</li>
                    <li>자산 추가 시 '티커(Ticker)'를 입력해야 가격이 갱신됩니다.</li>
                    <li>우측 상단의 '가격 동기화' 버튼을 눌러 업데이트하세요.</li>
                </ul>
            </div>

        </div>
    );
};
