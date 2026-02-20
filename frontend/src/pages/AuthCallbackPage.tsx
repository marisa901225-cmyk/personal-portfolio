import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSettings } from '../../hooks/SettingsContext';

/**
 * 네이버 로그인 콜백 페이지
 * 
 * 네이버 로그인 후 리다이렉트되는 페이지입니다.
 * URL의 code와 state를 받아서 백엔드로 전송하고 HttpOnly 쿠키를 발급받습니다.
 */
export const AuthCallbackPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { settings, setSettings } = useSettings();
    const [status, setStatus] = React.useState<'loading' | 'success' | 'error'>('loading');
    const [errorMessage, setErrorMessage] = React.useState<string>('');

    const calledRef = React.useRef(false);

    useEffect(() => {
        const handleCallback = async () => {
            if (calledRef.current) return;
            calledRef.current = true;

            // URL에서 code와 state 추출
            const code = searchParams.get('code');
            const state = searchParams.get('state');
            const error = searchParams.get('error');
            const errorDescription = searchParams.get('error_description');

            // 에러 처리
            if (error) {
                setStatus('error');
                setErrorMessage(errorDescription || '네이버 로그인 중 오류가 발생했습니다.');
                return;
            }

            if (!code || !state) {
                setStatus('error');
                setErrorMessage('인증 코드가 없습니다. 다시 로그인해주세요.');
                return;
            }

            try {
                // 백엔드로 code와 state 전송하여 쿠키 기반 로그인 처리
                const response = await fetch(
                    `${settings.serverUrl}/api/auth/naver/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
                    { credentials: 'include' }
                );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || '로그인 처리 중 오류가 발생했습니다.');
                }

                const data = await response.json();
                if (!data?.access_token) {
                    throw new Error('로그인 토큰을 받지 못했습니다. 다시 로그인해주세요.');
                }

                // 쿠키 기반 인증 상태 및 사용자 정보 저장
                setSettings((prev) => ({
                    ...prev,
                    cookieAuth: true,
                    naverUser: data.user,
                }));

                setStatus('success');

                // 1초 후 메인 페이지로 리다이렉트
                setTimeout(() => {
                    navigate('/');
                }, 1000);
            } catch (error: any) {
                setStatus('error');
                setErrorMessage(error.message || '알 수 없는 오류가 발생했습니다.');
            }
        };

        handleCallback();
    }, [searchParams, settings.serverUrl, setSettings, navigate]);

    if (status === 'loading') {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100">
                <div className="text-center">
                    <div className="inline-block animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-indigo-600 mb-4"></div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 처리 중...</h2>
                    <p className="text-slate-600">잠시만 기다려주세요.</p>
                </div>
            </div>
        );
    }

    if (status === 'success') {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-green-50 to-emerald-100">
                <div className="text-center">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500 rounded-full mb-4">
                        <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 성공!</h2>
                    <p className="text-slate-600">메인 페이지로 이동합니다...</p>
                </div>
            </div>
        );
    }

    // error 상태
    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-rose-100">
            <div className="max-w-md w-full bg-white rounded-2xl shadow-lg p-8">
                <div className="text-center mb-6">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-red-500 rounded-full mb-4">
                        <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 실패</h2>
                    <p className="text-slate-600 mb-4">{errorMessage}</p>
                    <button
                        onClick={() => navigate('/settings')}
                        className="px-6 py-3 bg-indigo-600 text-white rounded-lg font-semibold hover:bg-indigo-700 transition-colors"
                    >
                        설정으로 돌아가기
                    </button>
                </div>
            </div>
        </div>
    );
};
