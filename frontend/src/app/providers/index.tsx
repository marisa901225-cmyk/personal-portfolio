import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { QueryProvider } from './QueryProvider';
import { SettingsProvider } from '@hooks/useSettings';
import { ToastProvider } from '../../contexts/ToastContext';

interface AppProvidersProps {
    children: React.ReactNode;
}

/**
 * 앱 전역 프로바이더를 한 곳에 모아 관리합니다.
 * - SettingsProvider (앱 설정 및 인증 상태)
 * - React Query (서버 상태 관리)
 * - React Router (URL 기반 라우팅)
 */
export const AppProviders: React.FC<AppProvidersProps> = ({ children }) => {
    return (
        <ToastProvider>
            <SettingsProvider>
                <QueryProvider>
                    <BrowserRouter>
                        {children}
                    </BrowserRouter>
                </QueryProvider>
            </SettingsProvider>
        </ToastProvider>
    );
};
