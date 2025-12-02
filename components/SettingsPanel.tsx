import React from 'react';
import { Server } from 'lucide-react';
import { AppSettings, TargetIndexAllocation } from '../types';

interface SettingsPanelProps {
  settings: AppSettings;
  onSettingsChange: (next: AppSettings) => void;
  onBackToDashboard: () => void;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  settings,
  onSettingsChange,
  onBackToDashboard,
}) => {
  const handleAllocationChange = (
    index: number,
    field: 'indexGroup' | 'targetWeight',
    value: string
  ) => {
    const current: TargetIndexAllocation[] = [...(settings.targetIndexAllocations || [])];
    const existing = current[index] || { indexGroup: '', targetWeight: 0 };
    const updated: TargetIndexAllocation = {
      ...existing,
      [field]: field === 'targetWeight' ? Number(value) || 0 : value,
    };
    current[index] = updated;
    onSettingsChange({
      ...settings,
      targetIndexAllocations: current,
    });
  };

  const handleAddAllocationRow = () => {
    const current: TargetIndexAllocation[] = [...(settings.targetIndexAllocations || [])];
    current.push({ indexGroup: '', targetWeight: 0 });
    onSettingsChange({
      ...settings,
      targetIndexAllocations: current,
    });
  };

  const handleRemoveAllocationRow = (index: number) => {
    const current: TargetIndexAllocation[] = [...(settings.targetIndexAllocations || [])];
    if (current.length <= 1) {
      return;
    }
    current.splice(index, 1);
    onSettingsChange({
      ...settings,
      targetIndexAllocations: current,
    });
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 max-w-lg mx-auto animate-fade-in-up">
      <div className="flex items-center space-x-3 mb-6 pb-4 border-b border-slate-100">
        <div className="p-2 bg-slate-100 rounded-lg">
          <Server size={24} className="text-slate-600" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-slate-800">홈서버 연결 설정</h2>
          <p className="text-sm text-slate-500">Tailscale을 통한 백엔드 연결</p>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">홈서버 API URL</label>
          <input
            type="text"
            className="w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors font-mono text-sm"
            placeholder="http://100.x.y.z:8000"
            value={settings.serverUrl}
            onChange={(e) =>
              onSettingsChange({
                ...settings,
                serverUrl: e.target.value,
              })
            }
          />
          <p className="text-xs text-slate-500 mt-2">
            * Tailscale Machine IP와 Port를 입력하세요.
            <br />
            * 예: http://100.101.102.103:8000
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

        <div className="pt-2 border-t border-slate-100">
          <h3 className="text-sm font-semibold text-slate-800 mb-2">목표 지수 비중</h3>
          <p className="text-xs text-slate-500 mb-3">
            예: S&amp;P500 6 / NASDAQ100 3 / BOND+ETC 1 처럼 비율을 넣으면, 합계 기준으로 자동으로 100%로 환산됩니다.
          </p>
          <div className="space-y-2">
            {(settings.targetIndexAllocations || []).map((alloc, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  type="text"
                  className="flex-1 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  placeholder="지수 이름 (예: S&P500)"
                  value={alloc.indexGroup}
                  onChange={(e) => handleAllocationChange(index, 'indexGroup', e.target.value)}
                />
                <input
                  type="number"
                  className="w-20 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  placeholder="비율"
                  value={alloc.targetWeight || ''}
                  min={0}
                  onChange={(e) => handleAllocationChange(index, 'targetWeight', e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => handleRemoveAllocationRow(index)}
                  className="px-2 py-1 text-[11px] text-slate-400 hover:text-red-500"
                  disabled={(settings.targetIndexAllocations || []).length <= 1}
                >
                  삭제
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={handleAddAllocationRow}
            className="mt-3 text-xs text-indigo-600 hover:text-indigo-700"
          >
            + 지수 비중 추가
          </button>
        </div>

        <div className="pt-4">
          <button
            onClick={onBackToDashboard}
            className="w-full py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all"
          >
            설정 저장 및 돌아가기
          </button>
        </div>
      </div>
    </div>
  );
};
