import React, { useState } from 'react';
import { Server, Sliders } from 'lucide-react';
import { AppSettings, TargetIndexAllocation } from '../lib/types';
import { ApiClient, BackendFxTransaction } from '@/shared/api/client';
import { alertError } from '@/shared/errors';
import { ServerTab } from './settings/ServerTab';
import { PortfolioTab } from './settings/PortfolioTab';

type SettingsTab = 'server' | 'portfolio';

interface SettingsPanelProps {
  settings: AppSettings;
  onSettingsChange: (next: AppSettings) => void;
  onBackToDashboard: () => void;
}

interface TabButtonProps {
  tab: SettingsTab;
  icon: any;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

const TabButton: React.FC<TabButtonProps> = ({ tab, icon: Icon, label, isActive, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    data-tab={tab}
    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium rounded-xl transition-all ${isActive
      ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
      }`}
  >
    <Icon size={18} />
    <span>{label}</span>
  </button>
);

export const SettingsPanel: React.FC<SettingsPanelProps> = ({
  settings,
  onSettingsChange,
  onBackToDashboard,
}) => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('server');

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

    try {
      const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);
      const data = await apiClient.checkHealth();
      if (data && data.status === 'ok') {
        alert('백엔드 서버가 정상적으로 응답하고 있습니다.');
      } else {
        alert('서버와 연결은 되었지만 /health 응답이 예상과 다릅니다.');
      }
    } catch (error) {
      alertError('Health check error', error, {
        default: `백엔드 서버 상태를 확인하지 못했습니다.\nURL: ${settings.serverUrl}`,
        network: `백엔드 서버에 연결할 수 없습니다.\nURL: ${settings.serverUrl}`,
      });
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

    try {
      const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);
      const data = await apiClient.fetchUsdKrwFxRate();
      const rateNum = data?.rate;

      if (!rateNum || !Number.isFinite(rateNum)) {
        alert('응답에서 환율 값을 읽지 못했습니다.');
        return;
      }

      onSettingsChange({
        ...settings,
        usdFxNow: rateNum,
      });
    } catch (error) {
      alertError('FX rate fetch error', error, {
        default: '환율을 불러오지 못했습니다.\n잠시 후 다시 시도해주세요.',
        unauthorized:
          'API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.',
        rateLimited: '시세 제공자가 너무 많은 요청을 받아 잠시 차단했습니다.\n잠시 후 다시 시도해주세요.',
        network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
      });
    }
  };

  const handleApplyFxBaseFromHistory = async () => {
    if (!settings.serverUrl || !settings.serverUrl.trim()) {
      alert('먼저 홈서버 API URL을 입력해주세요.');
      return;
    }
    if (!settings.apiToken) {
      alert('먼저 API 비밀번호를 입력해주세요.');
      return;
    }

    const fetchAll = async (client: ApiClient): Promise<BackendFxTransaction[]> => {
      const records: BackendFxTransaction[] = [];
      let beforeId: number | undefined;

      while (true) {
        const batch = await client.fetchFxTransactions({
          limit: 500,
          beforeId,
          kind: 'BUY',
        });
        if (batch.length === 0) break;
        records.push(...batch);
        if (batch.length < 500) break;
        beforeId = batch[batch.length - 1].id;
      }

      return records;
    };

    try {
      const apiClient = new ApiClient(settings.serverUrl, settings.apiToken);
      const records = await fetchAll(apiClient);

      let weightedSum = 0;
      let weightTotal = 0;
      let fallbackSum = 0;
      let fallbackCount = 0;

      records.forEach((record) => {
        const fxAmount = record.fx_amount ?? null;
        let rate = record.rate ?? null;
        if (rate == null && fxAmount != null && record.krw_amount != null && fxAmount !== 0) {
          rate = record.krw_amount / fxAmount;
        }
        if (rate == null || !Number.isFinite(rate)) return;

        if (fxAmount && Number.isFinite(fxAmount) && fxAmount > 0) {
          weightedSum += rate * fxAmount;
          weightTotal += fxAmount;
        } else {
          fallbackSum += rate;
          fallbackCount += 1;
        }
      });

      let avgRate: number | null = null;
      if (weightTotal > 0) {
        avgRate = weightedSum / weightTotal;
      } else if (fallbackCount > 0) {
        avgRate = fallbackSum / fallbackCount;
      }

      if (!avgRate || !Number.isFinite(avgRate)) {
        alert('환전 평균 환율을 계산할 수 없습니다.');
        return;
      }

      const rounded = Math.round(avgRate * 100) / 100;
      onSettingsChange({
        ...settings,
        usdFxBase: rounded,
      });
      alert(`환전 평균 환율 ${rounded} 적용 완료 (매수 ${records.length}건 기준)`);
    } catch (error) {
      alertError('FX average apply error', error, {
        default: '환전 평균 환율을 불러오지 못했습니다.\n잠시 후 다시 시도해주세요.',
        unauthorized:
          'API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.',
        network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
      });
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 max-w-lg mx-auto animate-fade-in-up">
      {/* 탭 버튼 */}
      <div className="flex gap-2 mb-6">
        <TabButton
          tab="server"
          icon={Server}
          label="서버 연결"
          isActive={activeTab === 'server'}
          onClick={() => setActiveTab('server')}
        />
        <TabButton
          tab="portfolio"
          icon={Sliders}
          label="포트폴리오 & 외관"
          isActive={activeTab === 'portfolio'}
          onClick={() => setActiveTab('portfolio')}
        />
      </div>

      {/* 탭 컨텐츠 */}
      <div className="min-h-[300px]">
        {activeTab === 'server' && (
          <ServerTab
            settings={settings}
            onSettingsChange={onSettingsChange}
            onCheckHealth={handleCheckHealth}
          />
        )}
        {activeTab === 'portfolio' && (
          <PortfolioTab
            settings={settings}
            onSettingsChange={onSettingsChange}
            onFetchFxRate={handleFetchFxRate}
            onApplyFxBaseFromHistory={handleApplyFxBaseFromHistory}
            onAllocationChange={handleAllocationChange}
            onAddAllocationRow={handleAddAllocationRow}
            onRemoveAllocationRow={handleRemoveAllocationRow}
          />
        )}
      </div>

      {/* 저장 버튼 */}
      <div className="pt-4 mt-4 border-t border-slate-100">
        <button
          onClick={onBackToDashboard}
          className="w-full py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all"
        >
          설정 저장 및 돌아가기
        </button>
      </div>
    </div>
  );
};
