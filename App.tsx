import React, { useState, useEffect } from 'react';
import { LayoutDashboard, List, PlusCircle, Bell, Menu, X, Settings, RefreshCw } from 'lucide-react';
import { Asset, ViewState, AppSettings, TradeType, TradeRecord } from './types';
import { formatCurrency } from './constants';
import { Dashboard } from './components/Dashboard';
import { AssetList } from './components/AssetList';
import { AddAssetForm } from './components/AddAssetForm';
import { SettingsPanel } from './components/SettingsPanel';
import { usePortfolio } from './hooks/usePortfolio';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<ViewState>('DASHBOARD');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [settings, setSettings] = useState<AppSettings>({
    serverUrl: 'https://dlckdgn-nucboxg3-plus.tail5c2348.ts.net',
    targetIndexAllocations: [
      { indexGroup: 'S&P500', targetWeight: 6 },
      { indexGroup: 'NASDAQ100', targetWeight: 3 },
      { indexGroup: 'BOND+ETC', targetWeight: 1 },
    ],
  });
  const [authInput, setAuthInput] = useState('');
  const [showAuthModal, setShowAuthModal] = useState(true);

  const {
    assets,
    tradeHistory,
    historyData,
    isSyncing,
    addAsset,
    deleteAsset,
    tradeAsset,
    syncPrices,
    updateTicker,
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

  const handleUpdateTicker = (id: string, ticker?: string) => {
    void updateTicker(id, ticker);
  };

  const handleSyncPrices = async () => {
    if (!settings.serverUrl) {
      alert('설정에서 홈서버 URL을 입력해주세요.');
      setCurrentView('SETTINGS');
      return;
    }
    await syncPrices();
  };

  // 초기 로드 시 한 번 자동 가격 동기화 시도
  useEffect(() => {
    const hasTickers = assets.some(a => !!a.ticker);
    if (!settings.serverUrl || !hasTickers || !settings.apiToken) {
      return;
    }
    void handleSyncPrices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAuthSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!authInput.trim()) return;
    setSettings(prev => ({ ...prev, apiToken: authInput.trim() }));
    setShowAuthModal(false);
    setAuthInput('');
  };

  const NavItem = ({ view, icon: Icon, label }: { view: ViewState; icon: any; label: string }) => (
    <button
      onClick={() => {
        setCurrentView(view);
        setIsMobileMenuOpen(false);
      }}
      className={`flex items-center space-x-3 px-4 py-3 rounded-xl transition-all w-full md:w-auto ${
        currentView === view
          ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
          : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'
      }`}
    >
      <Icon size={20} />
      <span className="font-medium">{label}</span>
    </button>
  );

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col md:flex-row">
      {showAuthModal && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center px-4">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-sm p-6">
            <h2 className="text-lg font-bold text-slate-900 mb-2">API 비밀번호 입력</h2>
            <p className="text-xs text-slate-500 mb-4">
              백엔드 서버의 <code>API_TOKEN</code> 값과 동일한 비밀번호를 입력하세요.
              브라우저를 새로고침하면 다시 입력해야 합니다.
            </p>
            <form onSubmit={handleAuthSubmit} className="space-y-3">
              <div>
                <input
                  type="password"
                  autoFocus
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 text-sm"
                  placeholder="API 비밀번호"
                  value={authInput}
                  onChange={(e) => setAuthInput(e.target.value)}
                />
              </div>
              <button
                type="submit"
                className="w-full py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                포트폴리오 들어가기
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Sidebar (Desktop) */}
      <aside className="hidden md:flex flex-col w-64 bg-white border-r border-slate-200 h-screen sticky top-0">
        <div className="p-6 border-b border-slate-100">
          <div className="flex items-center space-x-2 text-indigo-600">
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-lg">P</span>
            </div>
            <span className="text-xl font-bold tracking-tight text-slate-900">MyPortfolio</span>
          </div>
        </div>

        <nav className="flex-1 p-4 space-y-2">
          <NavItem view="DASHBOARD" icon={LayoutDashboard} label="대시보드" />
          <NavItem view="LIST" icon={List} label="자산 목록" />
          <NavItem view="ADD" icon={PlusCircle} label="자산 추가" />
        </nav>

        <div className="p-4 border-t border-slate-100">
          <button
            onClick={() => setCurrentView('SETTINGS')}
            className={`flex items-center space-x-3 px-4 py-3 w-full rounded-xl transition-colors ${
              currentView === 'SETTINGS'
                ? 'bg-slate-100 text-slate-900'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
            }`}
          >
            <Settings size={20} />
            <span className="font-medium">서버 설정</span>
          </button>
        </div>
      </aside>

      {/* Mobile Header */}
      <div className="md:hidden bg-white border-b border-slate-200 p-4 sticky top-0 z-50 flex justify-between items-center">
        <div className="flex items-center space-x-2 text-indigo-600">
          <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-lg">P</span>
          </div>
          <span className="text-lg font-bold text-slate-900">MyPortfolio</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setCurrentView('SETTINGS')} className="p-2 text-slate-600">
            <Settings size={24} />
          </button>
          <button
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            className="p-2 text-slate-600"
          >
            {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </div>

      {/* Mobile Menu Overlay */}
      {isMobileMenuOpen && (
        <div className="md:hidden fixed inset-0 bg-white z-40 pt-20 px-4 space-y-2 animate-fade-in">
          <NavItem view="DASHBOARD" icon={LayoutDashboard} label="대시보드" />
          <NavItem view="LIST" icon={List} label="자산 목록" />
          <NavItem view="ADD" icon={PlusCircle} label="자산 추가" />
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 p-4 md:p-8 max-w-6xl mx-auto w-full">
        <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-900">
              {currentView === 'DASHBOARD'
                ? '대시보드'
                : currentView === 'LIST'
                ? '보유 자산'
                : currentView === 'ADD'
                ? '자산 추가'
                : '서버 설정'}
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              나만 보는 개인 포트폴리오 대시보드
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setIsHistoryOpen(!isHistoryOpen)}
              className="relative p-2 rounded-full border border-slate-200 bg-white text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
            >
              <Bell size={20} />
              {tradeHistory.length > 0 && (
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
                <button
                  type="button"
                  onClick={() => setIsHistoryOpen(false)}
                  className="text-xs text-slate-400 hover:text-slate-600"
                >
                  닫기
                </button>
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
                              className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                isBuy ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600'
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
                            className={`text-right text-[11px] font-semibold ${
                              pnl > 0
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
            targetIndexAllocations={settings.targetIndexAllocations}
            historyData={historyData}
          />
        )}
        {currentView === 'LIST' && (
          <AssetList
            assets={assets}
            onDelete={handleDeleteAsset}
            onTrade={handleTradeAsset}
            onUpdateTicker={handleUpdateTicker}
          />
        )}
        {currentView === 'ADD' && (
          <AddAssetForm
            onSave={handleAddAsset}
            onCancel={() => setCurrentView('DASHBOARD')}
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
          />
        )}
        {currentView === 'SETTINGS' && (
          <SettingsPanel
            settings={settings}
            onSettingsChange={setSettings}
            onBackToDashboard={() => setCurrentView('DASHBOARD')}
          />
        )}
      </main>

      {/* Mobile Bottom Navigation */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 px-6 py-3 flex justify-between items-center z-50 pb-safe">
        <button
          onClick={() => setCurrentView('DASHBOARD')}
          className={`flex flex-col items-center space-y-1 ${
            currentView === 'DASHBOARD' ? 'text-indigo-600' : 'text-slate-400'
          }`}
        >
          <LayoutDashboard size={24} />
          <span className="text-[10px] font-medium">홈</span>
        </button>
        <button
          onClick={() => setCurrentView('ADD')}
          className="flex flex-col items-center justify-center w-12 h-12 bg-indigo-600 rounded-full text-white shadow-lg shadow-indigo-200 -mt-6"
        >
          <PlusCircle size={24} />
        </button>
        <button
          onClick={() => setCurrentView('LIST')}
          className={`flex flex-col items-center space-y-1 ${
            currentView === 'LIST' ? 'text-indigo-600' : 'text-slate-400'
          }`}
        >
          <List size={24} />
          <span className="text-[10px] font-medium">목록</span>
        </button>
      </div>
    </div>
  );
};

export default App;
