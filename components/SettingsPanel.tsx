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

  const handleCheckHealth = async () => {
    if (!settings.serverUrl || !settings.serverUrl.trim()) {
      alert('먼저 홈서버 API URL을 입력해주세요.');
      return;
    }

    const baseUrl = settings.serverUrl.replace(/\/+$/, '');

    try {
      const response = await fetch(`${baseUrl}/health`);
      if (!response.ok) {
        alert(`서버에 연결했지만 상태 코드가 ${response.status} 입니다.`);
        return;
      }

      let data: any = null;
      try {
        data = await response.json();
      } catch {
        // JSON 파싱 실패는 무시 (단순 텍스트 응답일 수 있음)
      }

      if (data && data.status === 'ok') {
        alert('백엔드 서버가 정상적으로 응답하고 있습니다.');
      } else {
        alert('서버와 연결은 되었지만 /health 응답이 예상과 다릅니다.');
      }
    } catch (error) {
      console.error('Health check error', error);
      alert(
        '백엔드 서버에 연결할 수 없습니다.\n홈서버가 켜져 있고 Tailscale이 연결되어 있는지, 그리고 URL이 올바른지 확인하세요.',
      );
    }
  };

  const handleFetchFxRate = async () => {
    if (!settings.serverUrl || !settings.serverUrl.trim()) {
      alert('먼저 홈서버 API URL을 입력해주세요.');
      return;
    }
    if (!settings.apiToken) {
      alert('먼저 API 비밀번호를 입력해주세요.');
      return;
    }

    const baseUrl = settings.serverUrl.replace(/\/+$/, '');

    try {
      const response = await fetch(`${baseUrl}/api/kis/fx/usdkrw`, {
        method: 'GET',
        headers: {
          'X-API-Token': settings.apiToken,
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          alert('API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.');
          return;
        }
        alert(`환율을 불러오지 못했습니다. (HTTP ${response.status})`);
        return;
      }

      const data = await response.json();
      const rawRate = (data && (data.rate ?? data.fx_rate)) as number | string | undefined;
      const rateNum = typeof rawRate === 'number' ? rawRate : Number(rawRate);

      if (!rateNum || !Number.isFinite(rateNum)) {
        alert('응답에서 환율 값을 읽지 못했습니다.');
        return;
      }

      onSettingsChange({
        ...settings,
        usdFxNow: rateNum,
      });
    } catch (error) {
      console.error('FX rate fetch error', error);
      alert('증권사 환율을 불러오는 중 오류가 발생했습니다.\n잠시 후 다시 시도해주세요.');
    }
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
          <button
            type="button"
            onClick={handleCheckHealth}
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

        <div className="pt-2 border-t border-slate-100">
          <h3 className="text-sm font-semibold text-slate-800 mb-2">환율 설정 (대략적인 환차익/손)</h3>
          <p className="text-xs text-slate-500 mb-3">
            USD 자산 기준으로, 기준 환율과 현재 환율을 입력하면 대시보드에서 추정 환차익/환차손을 보여줍니다.
            정확한 값은 아니고, 대략적인 추세 확인용입니다.
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <label className="block text-xs font-medium text-slate-600 mb-1">
                기준 USD/KRW
              </label>
              <input
                type="number"
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="예: 1300"
                min={0}
                value={settings.usdFxBase ?? ''}
                onChange={(e) =>
                  onSettingsChange({
                    ...settings,
                    usdFxBase: e.target.value ? Number(e.target.value) || undefined : undefined,
                  })
                }
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs font-medium text-slate-600 mb-1">
                현재 USD/KRW
              </label>
              <input
                type="number"
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="예: 1350"
                min={0}
                value={settings.usdFxNow ?? ''}
                onChange={(e) =>
                  onSettingsChange({
                    ...settings,
                    usdFxNow: e.target.value ? Number(e.target.value) || undefined : undefined,
                  })
                }
              />
            </div>
            <button
              type="button"
              onClick={handleFetchFxRate}
              className="px-3 py-2 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 whitespace-nowrap"
            >
              증권사에서 불러오기
            </button>
          </div>
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
