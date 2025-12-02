import React, { useState } from 'react';
import { LayoutDashboard, List, PlusCircle, Bell, Menu, X, Settings, RefreshCw, Server } from 'lucide-react';
import { Asset, ViewState, AppSettings } from './types';
import { INITIAL_ASSETS } from './constants';
import { Dashboard } from './components/Dashboard';
import { AssetList } from './components/AssetList';
import { AddAssetForm } from './components/AddAssetForm';

const App: React.FC = () => {
  const [assets, setAssets] = useState<Asset[]>(INITIAL_ASSETS);
  const [currentView, setCurrentView] = useState<ViewState>('DASHBOARD');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [settings, setSettings] = useState<AppSettings>({
    serverUrl: 'http://100.x.y.z:8000' // Default example
  });
  const [isSyncing, setIsSyncing] = useState(false);

  const handleAddAsset = (newAsset: Asset) => {
    setAssets([...assets, newAsset]);
    setCurrentView('LIST');
  };

  const handleDeleteAsset = (id: string) => {
    if (window.confirm('정말 이 자산을 삭제하시겠습니까?')) {
      setAssets(assets.filter(a => a.id !== id));
    }
  };

  // Sync with Home Server
  const handleSyncPrices = async () => {
    if (!settings.serverUrl) {
        alert('설정에서 홈서버 URL을 입력해주세요.');
        setCurrentView('SETTINGS');
        return;
    }

    const tickers = assets.filter(a => a.ticker).map(a => a.ticker);
    if (tickers.length === 0) {
        alert('티커가 등록된 자산이 없습니다.');
        return;
    }

    setIsSyncing(true);
    try {
        const response = await fetch(`${settings.serverUrl}/api/prices`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ tickers }),
        });

        if (!response.ok) throw new Error('Failed to fetch');

        const priceMap = await response.json();
        
        // Update assets with new prices
        setAssets(prevAssets => prevAssets.map(asset => {
            if (asset.ticker && priceMap[asset.ticker]) {
                return { ...asset, currentPrice: priceMap[asset.ticker] };
            }
            return asset;
        }));

        alert('최신 가격 정보를 업데이트했습니다.');
    } catch (error) {
        console.error("Sync Error:", error);
        alert(`서버 연결 실패.\nURL: ${settings.serverUrl}\n홈서버가 켜져있고 Tailscale이 연결되었는지 확인하세요.`);
    } finally {
        setIsSyncing(false);
    }
  };

  const NavItem = ({ view, icon: Icon, label }: { view: ViewState, icon: any, label: string }) => (
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
             className={`flex items-center space-x-3 px-4 py-3 w-full rounded-xl transition-colors ${currentView === 'SETTINGS' ? 'bg-slate-100 text-slate-900' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'}`}
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
            <button onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)} className="p-2 text-slate-600">
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
             <NavItem view="SETTINGS" icon={Settings} label="서버 설정" />
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 p-4 md:p-8 max-w-7xl mx-auto w-full">
        <header className="flex justify-between items-center mb-8">
            <div>
                <h1 className="text-2xl font-bold text-slate-900">
                    {currentView === 'DASHBOARD' && '나의 자산 현황'}
                    {currentView === 'LIST' && '자산 상세 목록'}
                    {currentView === 'ADD' && '자산 추가하기'}
                    {currentView === 'SETTINGS' && '환경 설정'}
                </h1>
                <p className="text-slate-500 text-sm mt-1">오늘도 성공적인 투자를 기원합니다.</p>
            </div>
            <div className="flex space-x-3">
                {/* Sync Button */}
                <button 
                    onClick={handleSyncPrices}
                    disabled={isSyncing}
                    className={`flex items-center space-x-2 px-3 py-2 bg-indigo-50 text-indigo-600 rounded-lg border border-indigo-100 hover:bg-indigo-100 transition-colors ${isSyncing ? 'opacity-50 cursor-not-allowed' : ''}`}
                    title="홈서버에서 최신 가격 가져오기"
                >
                    <RefreshCw size={18} className={isSyncing ? 'animate-spin' : ''} />
                    <span className="hidden md:inline font-medium">가격 동기화</span>
                </button>
                
                <button className="p-2 bg-white rounded-full border border-slate-200 text-slate-400 hover:text-indigo-600 hover:border-indigo-200 transition-all shadow-sm relative">
                    <Bell size={20} />
                    <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-white"></span>
                </button>
            </div>
        </header>

        {currentView === 'DASHBOARD' && <Dashboard assets={assets} />}
        {currentView === 'LIST' && <AssetList assets={assets} onDelete={handleDeleteAsset} />}
        {currentView === 'ADD' && (
            <AddAssetForm 
                onSave={handleAddAsset} 
                onCancel={() => setCurrentView('DASHBOARD')} 
            />
        )}
        {currentView === 'SETTINGS' && (
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
                            onChange={(e) => setSettings({ ...settings, serverUrl: e.target.value })}
                        />
                        <p className="text-xs text-slate-500 mt-2">
                            * Tailscale Machine IP와 Port를 입력하세요.<br/>
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

                    <div className="pt-4">
                        <button 
                            onClick={() => setCurrentView('DASHBOARD')}
                            className="w-full py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all"
                        >
                            설정 저장 및 돌아가기
                        </button>
                    </div>
                </div>
            </div>
        )}
      </main>

      {/* Mobile Bottom Navigation (Sticky) */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 px-6 py-3 flex justify-between items-center z-50 pb-safe">
        <button 
            onClick={() => setCurrentView('DASHBOARD')}
            className={`flex flex-col items-center space-y-1 ${currentView === 'DASHBOARD' ? 'text-indigo-600' : 'text-slate-400'}`}
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
            className={`flex flex-col items-center space-y-1 ${currentView === 'LIST' ? 'text-indigo-600' : 'text-slate-400'}`}
        >
            <List size={24} />
            <span className="text-[10px] font-medium">목록</span>
        </button>
      </div>
    </div>
  );
};

export default App;