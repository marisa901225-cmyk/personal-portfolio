import React from 'react';
import { Server } from 'lucide-react';
import { AppSettings } from '../../lib/types';
import { cn, ui } from '@/shared/ui';

interface ServerTabProps {
    settings: AppSettings;
    onSettingsChange: (next: AppSettings) => void;
    onCheckHealth: () => void;
}

export const ServerTab: React.FC<ServerTabProps> = ({ settings, onSettingsChange, onCheckHealth }) => (
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
