import React, { useState, useEffect, useRef } from 'react';
import { LayoutDashboard, List, PlusCircle, Bell, Settings, RefreshCw, Lock, KeyRound, ScrollText, ArrowLeftRight, Wallet, Sparkles, AlertCircle, X } from 'lucide-react';
import { Asset, ViewState, TradeType, TradeRecord, AssetCategory } from './lib/types';
import { formatCurrency } from './lib/utils/constants';
import { APP_ERROR_EVENT } from './lib/utils/errors';
import { Dashboard } from './components/Dashboard';
import { AssetList } from './components/AssetList';
import { AddAssetForm } from './components/AddAssetForm';
import { SettingsPanel } from './components/SettingsPanel';
import { TradeHistoryAll } from './components/TradeHistoryAll';
import { ExchangeHistory } from './components/ExchangeHistory';
import { ExpensesDashboard } from './components/ExpensesDashboard';
import { AiReportDashboard } from './components/AiReportDashboard';

import { NotificationModal } from './components/NotificationModal';
import { InvestmentQuote } from './components/InvestmentQuote';
import { usePortfolio } from './hooks/usePortfolio';
import { useSettings } from './hooks/useSettings';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<ViewState>('DASHBOARD');
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [hasUnreadHistory, setHasUnreadHistory] = useState(false);
  const { settings, setSettings, saveSettingsToServer } = useSettings();
  const [authInput, setAuthInput] = useState('');
  const [showAuthModal, setShowAuthModal] = useState(true);
  const [appError, setAppError] = useState<string | null>(null);
  const [syncNotification, setSyncNotification] = useState<{ isOpen: boolean; title: string; message: string }>({
    isOpen: false,
    title: '',
    message: '',
  });
  const errorTimerRef = useRef<number | null>(null);

  const {
    assets,
    tradeHistory,
    historyData,
    summaryFromServer,
    isSyncing,
    addAsset,
    deleteAsset,
    tradeAsset,
    syncPrices,
    updateAsset,
    updateCashBalance,
    restoreFromBackup,
    yearlyCashflows,
    apiClient,
    reload,
  } = usePortfolio(settings);

  const handleAddAsset = async (newAsset: Asset) => {
    await addAsset(newAsset);
    setCurrentView('LIST');
  };

  const handleDeleteAsset = (id: string) => {
    if (!window.confirm('정말 이 자산을 삭제하시겠습니까?')) return;
    void deleteAsset(id);
  };

  const handleTradeAsset = (id: string, type: TradeType, quantity: number, price: number) => {
    void tradeAsset(id, type, quantity, price);
  };

  const handleUpdateAsset = (
    id: string,
    updates: {
      name?: string;
      ticker?: string;
      indexGroup?: string;
      category?: AssetCategory;
      amount?: number;
      purchasePrice?: number;
      currentPrice?: number;
    },
  ) => {
    void updateAsset(id, updates);
  };

  const handleSyncPrices = async () => {
    if (!settings.serverUrl) {
      alert('설정에서 홈서버 URL을 입력해주세요.');
      setCurrentView('SETTINGS');
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

  // 초기 로드 시 한 번 자동 가격 동기화 시도
  useEffect(() => {
    const hasTickers = assets.some(a => !!a.ticker);
    if (!settings.serverUrl || !hasTickers || !settings.apiToken) {
      return;
    }
    void syncPrices({ createSnapshot: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 새 거래 내역이 생기면 알림 점 표시 (히스토리 패널이 닫혀 있을 때만)
  const prevTradeCountRef = useRef(tradeHistory.length);
  useEffect(() => {
    const prevCount = prevTradeCountRef.current;
    const currentCount = tradeHistory.length;
    prevTradeCountRef.current = currentCount;

    // 실제로 새 거래가 추가되었을 때만 빨간불 켜기
    if (currentCount > prevCount && !isHistoryOpen) {
      setHasUnreadHistory(true);
    }
  }, [tradeHistory.length, isHistoryOpen]);

  const handleAuthSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!authInput.trim()) return;
    setSettings(prev => ({ ...prev, apiToken: authInput.trim() }));
    setShowAuthModal(false);
    setAuthInput('');
  };

  const dismissAppError = () => {
    setAppError(null);
    if (errorTimerRef.current !== null) {
      window.clearTimeout(errorTimerRef.current);
      errorTimerRef.current = null;
    }
  };

  useEffect(() => {
    const handleAppError = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (!detail) return;
      setAppError(detail);
      if (errorTimerRef.current !== null) {
        window.clearTimeout(errorTimerRef.current);
      }
      errorTimerRef.current = window.setTimeout(() => {
        setAppError(null);
        errorTimerRef.current = null;
      }, 8000);
    };

    window.addEventListener(APP_ERROR_EVENT, handleAppError as EventListener);
    return () => {
      window.removeEventListener(APP_ERROR_EVENT, handleAppError as EventListener);
      if (errorTimerRef.current !== null) {
        window.clearTimeout(errorTimerRef.current);
        errorTimerRef.current = null;
      }
    };
  }, []);

  // settings persistence & backend sync are handled by useSettings

  const NavItem = ({ view, icon: Icon, label }: { view: ViewState; icon: any; label: string }) => (
    <button
      onClick={() => {
        setCurrentView(view);
      }}
      className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all w-full md:w-auto ${currentView === view
        ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
        }`}
    >
      <Icon size={20} />
      <span className="font-medium">{label}</span>
    </button>
  );

  // 배경 스타일 계산
  const bgStyle: React.CSSProperties = settings.bgEnabled && settings.bgImageData
    ? {
      backgroundImage: `url(${settings.bgImageData})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundAttachment: 'fixed',
    }
    : {};

  // 카드에 적용할 글래스 클래스
  const cardGlassClass = settings.bgEnabled
    ? `backdrop-blur-[${settings.bgBlur ?? 8}px] bg-white/${settings.cardOpacity ?? 85}`
    : '';

  return (
    <div
      className={`min-h-screen flex flex-col md:flex-row ${!settings.bgEnabled ? 'bg-slate-50' : ''}`}
      style={bgStyle}
    >
      {showAuthModal && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4 animate-fade-in"
        >
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all">
            {/* Header with gradient */}
            <div className="relative bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 p-6 text-white overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
              <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>

              <div className="relative flex items-center gap-3">
                <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                  <Lock size={24} />
                </div>
                <div>
                  <h3 className="text-xl font-bold">포트폴리오 로그인</h3>
                  <p className="text-sm text-indigo-100 mt-0.5">비밀번호를 입력하세요</p>
                </div>
              </div>
            </div>

            <form onSubmit={handleAuthSubmit} className="p-6 space-y-6">
              <div className="space-y-3">
                <label className="block text-sm font-semibold text-slate-700">
                  API 비밀번호
                </label>

                <div className="relative">
                  <input
                    type="password"
                    autoFocus
                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                    placeholder="비밀번호 입력"
                    value={authInput}
                    onChange={(e) => setAuthInput(e.target.value)}
                  />
                  <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                    <KeyRound size={18} />
                  </div>
                </div>

                <p className="text-xs text-slate-400 flex items-center gap-1">
                  <span className="w-1 h-1 bg-slate-400 rounded-full"></span>
                  백엔드 서버의 <code className="px-1 py-0.5 bg-slate-100 rounded text-slate-600">API_TOKEN</code> 값과 동일한 비밀번호를 입력하세요
                </p>
              </div>

              <button
                type="submit"
                className="w-full py-3 bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-sm font-semibold rounded-xl hover:shadow-lg hover:scale-[1.02] transition-all duration-200"
              >
                포트폴리오 들어가기
              </button>
            </form>
          </div>
        </div>
      )}

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
          <NavItem view="DASHBOARD" icon={LayoutDashboard} label="대시보드" />
          <NavItem view="LIST" icon={List} label="자산 목록" />
          <NavItem view="TRADES" icon={ScrollText} label="거래 내역" />
          <NavItem view="EXCHANGE" icon={ArrowLeftRight} label="환전 내역" />
          <NavItem view="EXPENSES" icon={Wallet} label="가계부" />
          <NavItem view="AI_REPORT" icon={Sparkles} label="AI 리포트" />
          <NavItem view="ADD" icon={PlusCircle} label="자산 추가" />
        </nav>

        <div className={`p-4 ${settings.bgEnabled ? 'border-t border-white/20' : 'border-t border-slate-100'}`}>
          <button
            onClick={() => setCurrentView('SETTINGS')}
            className={`flex items-center space-x-3 px-4 py-3 w-full rounded-xl transition-colors ${currentView === 'SETTINGS'
              ? 'bg-slate-100 text-slate-900'
              : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
              }`}
          >
            <Settings size={20} />
            <span className="font-medium">설정</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-4 md:p-8 max-w-6xl mx-auto w-full">
        {appError && (
          <div
            role="alert"
            className="mb-4 flex items-start justify-between gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-sm"
          >
            <div className="flex items-start gap-2">
              <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-500" />
              <p className="whitespace-pre-line">{appError}</p>
            </div>
            <button
              type="button"
              onClick={dismissAppError}
              className="rounded-lg p-1 text-red-400 transition-colors hover:bg-red-100 hover:text-red-600"
              aria-label="오류 알림 닫기"
            >
              <X size={16} />
            </button>
          </div>
        )}
        <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-900">
              {currentView === 'DASHBOARD'
                ? '대시보드'
                : currentView === 'LIST'
                  ? '보유 자산'
                  : currentView === 'TRADES'
                    ? '거래 내역'
                    : currentView === 'EXCHANGE'
                      ? '환전 내역'
                      : currentView === 'EXPENSES'
                        ? '가계부'
                        : currentView === 'AI_REPORT'
                          ? 'AI 리포트'
                          : currentView === 'ADD'
                            ? '자산 추가'
                            : '서버 설정'}
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              {currentView === 'DASHBOARD'
                ? '자산 현황 한눈에 보기'
                : currentView === 'LIST'
                  ? '자산 관리 및 거래'
                  : currentView === 'TRADES'
                    ? '전체 거래 기록 조회'
                    : currentView === 'EXCHANGE'
                      ? '환전 기록 조회 및 수정'
                      : currentView === 'EXPENSES'
                        ? '월별 지출/수입 분석'
                        : currentView === 'AI_REPORT'
                          ? '가계부 + 투자 리포트 생성'
                          : currentView === 'ADD'
                            ? '새로운 자산 등록'
                            : '연결 및 환경 설정'}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                const next = !isHistoryOpen;
                setIsHistoryOpen(next);
                if (next) {
                  setHasUnreadHistory(false);
                }
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
                    onClick={() => {
                      setCurrentView('TRADES');
                      setIsHistoryOpen(false);
                      setHasUnreadHistory(false);
                    }}
                    className="text-xs text-indigo-600 hover:text-indigo-700"
                  >
                    전체 보기
                  </button>
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
                  {tradeHistory.map((trade: TradeRecord) => {
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

        {currentView === 'DASHBOARD' && (
          <Dashboard
            assets={assets}
            backendSummary={summaryFromServer}
            usdFxBase={settings.usdFxBase}
            usdFxNow={settings.usdFxNow}
            targetIndexAllocations={settings.targetIndexAllocations}
            historyData={historyData}
            yearlyCashflows={yearlyCashflows}
            benchmarkName={settings.benchmarkName}
            benchmarkReturn={settings.benchmarkReturn}
            apiClient={apiClient}
            onReload={reload}
          />
        )}
        {currentView === 'LIST' && (
          <AssetList
            assets={assets}
            onDelete={handleDeleteAsset}
            onTrade={handleTradeAsset}
            onUpdateAsset={handleUpdateAsset}
            onUpdateCash={updateCashBalance}
            onRestoreFromBackup={restoreFromBackup}
            usdFxNow={settings.usdFxNow}
            indexGroupOptions={settings.targetIndexAllocations?.map(a => a.indexGroup) || []}
          />
        )}
        {currentView === 'TRADES' && (
          <TradeHistoryAll
            variant="page"
            assets={assets}
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
          />
        )}
        {currentView === 'EXCHANGE' && (
          <ExchangeHistory
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
            onFxBaseUpdated={(value) => setSettings((prev) => ({ ...prev, usdFxBase: value }))}
          />
        )}
        {currentView === 'EXPENSES' && (
          <ExpensesDashboard
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
          />
        )}
        {currentView === 'AI_REPORT' && (
          <AiReportDashboard
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
          />
        )}
        {currentView === 'ADD' && (
          <div className="space-y-4">
            <AddAssetForm
              onSave={handleAddAsset}
              onCancel={() => setCurrentView('DASHBOARD')}
              serverUrl={settings.serverUrl}
              apiToken={settings.apiToken}
            />
          </div>
        )}
        {currentView === 'SETTINGS' && (
          <SettingsPanel
            settings={settings}
            onSettingsChange={setSettings}
            onBackToDashboard={() => {
              void saveSettingsToServer(settings);
              setCurrentView('DASHBOARD');
            }}
          />
        )}
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

export default App;
