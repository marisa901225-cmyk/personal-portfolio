import React, { useState } from 'react';
import { Server, Palette, Sliders } from 'lucide-react';
import { AppSettings, TargetIndexAllocation } from '../types';
import { ApiClient, BackendFxTransaction } from '../backendClient';
import { alertError } from '../errors';

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

interface ServerTabProps {
  settings: AppSettings;
  onSettingsChange: (next: AppSettings) => void;
  onCheckHealth: () => void;
}

const ServerTab: React.FC<ServerTabProps> = ({ settings, onSettingsChange, onCheckHealth }) => (
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

interface PortfolioTabProps {
  settings: AppSettings;
  onSettingsChange: (next: AppSettings) => void;
  onFetchFxRate: () => void;
  onApplyFxBaseFromHistory: () => void;
  onAllocationChange: (
    index: number,
    field: 'indexGroup' | 'targetWeight',
    value: string
  ) => void;
  onAddAllocationRow: () => void;
  onRemoveAllocationRow: (index: number) => void;
}

const PortfolioTab: React.FC<PortfolioTabProps> = ({
  settings,
  onSettingsChange,
  onFetchFxRate,
  onApplyFxBaseFromHistory,
  onAllocationChange,
  onAddAllocationRow,
  onRemoveAllocationRow,
}) => (
  <div className="space-y-5 animate-fade-in">
    {/* 환율 설정 */}
    <div>
      <div className="flex items-center space-x-2 mb-3">
        <div className="p-1.5 bg-emerald-100 rounded-lg">
          <Sliders size={16} className="text-emerald-600" />
        </div>
        <h3 className="text-sm font-semibold text-slate-800">환율 설정</h3>
      </div>
      <p className="text-xs text-slate-500 mb-3">
        USD 자산 기준으로, 기준 환율과 현재 환율을 입력하면 대시보드에서 추정 환차익/환차손을 보여줍니다.
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
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={onFetchFxRate}
            className="px-3 py-2 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 whitespace-nowrap"
          >
            증권사에서 불러오기
          </button>
          <button
            type="button"
            onClick={onApplyFxBaseFromHistory}
            className="px-3 py-2 rounded-lg border border-slate-200 text-[11px] text-slate-600 hover:border-indigo-400 hover:text-indigo-600 whitespace-nowrap"
          >
            환전 평균 적용
          </button>
        </div>
      </div>
    </div>

    {/* 목표 지수 비중 */}
    <div className="pt-3 border-t border-slate-100">
      <h3 className="text-sm font-semibold text-slate-800 mb-2">목표 지수 비중</h3>
      <p className="text-xs text-slate-500 mb-3">
        예: S&amp;P500 6 / NASDAQ100 3 / BOND+ETC 1 처럼 상대 비중을 입력하거나, 60 / 30 / 10 처럼 합계가 100이 되도록 입력하면
        자동으로 100% 기준으로 환산됩니다. (합계가 100이면 각 값을 %로 그대로 사용합니다.)
      </p>
      <div className="space-y-2">
        {(settings.targetIndexAllocations || []).map((alloc, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              type="text"
              className="flex-1 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="지수 이름 (예: S&P500)"
              value={alloc.indexGroup}
              onChange={(e) => onAllocationChange(index, 'indexGroup', e.target.value)}
            />
            <input
              type="number"
              className="w-20 px-3 py-2 rounded-lg border border-slate-200 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="비율"
              value={alloc.targetWeight || ''}
              min={0}
              step="any"
              onChange={(e) => onAllocationChange(index, 'targetWeight', e.target.value)}
            />
            <button
              type="button"
              onClick={() => onRemoveAllocationRow(index)}
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
        onClick={onAddAllocationRow}
        className="mt-3 text-xs text-indigo-600 hover:text-indigo-700"
      >
        + 지수 비중 추가
      </button>
    </div>

    {/* 외관 설정 */}
    <div className="pt-3 border-t border-slate-100">
      <div className="flex items-center space-x-2 mb-3">
        <div className="p-1.5 bg-violet-100 rounded-lg">
          <Palette size={16} className="text-violet-600" />
        </div>
        <h3 className="text-sm font-semibold text-slate-800">외관 설정</h3>
      </div>

      {/* 배경 이미지 토글 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-slate-700">배경 이미지 사용</p>
          <p className="text-xs text-slate-400">활성화하면 카드에 글래스 효과가 적용됩니다</p>
        </div>
        <button
          type="button"
          onClick={() =>
            onSettingsChange({
              ...settings,
              bgEnabled: !settings.bgEnabled,
            })
          }
          className={`relative w-12 h-6 rounded-full transition-colors ${settings.bgEnabled ? 'bg-indigo-600' : 'bg-slate-300'
            }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${settings.bgEnabled ? 'translate-x-6' : 'translate-x-0'
              }`}
          />
        </button>
      </div>

      {settings.bgEnabled && (
        <div className="space-y-4 pl-2 border-l-2 border-indigo-200 animate-fade-in">
          {/* 배경 이미지 업로드 */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              배경 이미지 업로드
            </label>
            <div className="flex items-center gap-2">
              <label className="flex-1 flex items-center justify-center px-4 py-3 rounded-lg border-2 border-dashed border-slate-300 hover:border-indigo-400 cursor-pointer transition-colors">
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      // 파일 크기 체크 (5MB 제한)
                      if (file.size > 5 * 1024 * 1024) {
                        alert('이미지 파일이 너무 큽니다. 5MB 이하의 파일을 선택해주세요.');
                        return;
                      }
                      const reader = new FileReader();
                      reader.onload = (event) => {
                        const base64Data = event.target?.result as string;
                        onSettingsChange({
                          ...settings,
                          bgImageData: base64Data,
                        });
                      };
                      reader.readAsDataURL(file);
                    }
                    // input 초기화 (같은 파일 다시 선택 가능하도록)
                    e.target.value = '';
                  }}
                />
                <span className="text-xs text-slate-500">
                  {settings.bgImageData ? '다른 이미지 선택' : '이미지 파일 선택'}
                </span>
              </label>
              {settings.bgImageData && (
                <button
                  type="button"
                  onClick={() =>
                    onSettingsChange({
                      ...settings,
                      bgImageData: undefined,
                    })
                  }
                  className="px-3 py-2 text-xs text-red-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                >
                  삭제
                </button>
              )}
            </div>
            {/* 이미지 미리보기 */}
            {settings.bgImageData && (
              <div className="mt-3 rounded-lg overflow-hidden border border-slate-200">
                <img
                  src={settings.bgImageData}
                  alt="배경 이미지 미리보기"
                  className="w-full h-24 object-cover"
                />
              </div>
            )}
            <p className="text-[10px] text-slate-400 mt-2">
              * 이미지는 브라우저 로컬스토리지에 저장됩니다. (최대 5MB)
            </p>
          </div>

          {/* 카드 불투명도 */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-slate-600">
                카드 불투명도
              </label>
              <span className="text-xs text-slate-500">{settings.cardOpacity ?? 85}%</span>
            </div>
            <input
              type="range"
              min={50}
              max={100}
              value={settings.cardOpacity ?? 85}
              onChange={(e) =>
                onSettingsChange({
                  ...settings,
                  cardOpacity: Number(e.target.value),
                })
              }
              className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
            />
          </div>

          {/* 배경 흐림 강도 */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-slate-600">
                배경 흐림 (blur)
              </label>
              <span className="text-xs text-slate-500">{settings.bgBlur ?? 8}px</span>
            </div>
            <input
              type="range"
              min={0}
              max={20}
              value={settings.bgBlur ?? 8}
              onChange={(e) =>
                onSettingsChange({
                  ...settings,
                  bgBlur: Number(e.target.value),
                })
              }
              className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
            />
          </div>
        </div>
      )}
    </div>
  </div>
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
