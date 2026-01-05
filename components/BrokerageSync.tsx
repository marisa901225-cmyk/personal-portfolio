import React, { useState, useRef } from 'react';
import { Upload, CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react';
import { ApiClient } from '../lib/api';

interface BrokerageSyncProps {
    apiClient: ApiClient;
    onSyncComplete?: () => void;
    onClose?: () => void;
}

export const BrokerageSync: React.FC<BrokerageSyncProps> = ({ apiClient, onSyncComplete, onClose }) => {
    const [file, setFile] = useState<File | null>(null);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<{
        added: number;
        skipped: number;
        total_parsed: number;
        message: string;
    } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            const selectedFile = e.target.files[0];
            if (!selectedFile.name.endsWith('.xlsx')) {
                setError('Excel 파일(.xlsx)만 업로드 가능합니다.');
                return;
            }
            setFile(selectedFile);
            setError(null);
            setResult(null);
        }
    };

    const handleUpload = async () => {
        if (!file) return;

        setLoading(true);
        setError(null);
        setResult(null);

        try {
            const res = await apiClient.uploadStatement(file);
            setResult(res);
            if (onSyncComplete) onSyncComplete();
        } catch (err: any) {
            console.error('Sync failed:', err);
            setError(err.message || '파일 업로드 및 동기화 중 오류가 발생했습니다.');
        } finally {
            setLoading(false);
        }
    };

    const reset = () => {
        setFile(null);
        setResult(null);
        setError(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    return (
        <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl border border-slate-100">
            <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                    <Upload className="text-blue-500" size={24} />
                    증권사 내역 동기화
                </h2>
                {onClose && (
                    <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
                        <X size={20} />
                    </button>
                )}
            </div>

            <p className="text-sm text-slate-500 mb-6 leading-relaxed">
                삼성증권 등 증권사에서 내려받은 **거래내역 엑셀 파일**을 업로드하세요.
                입출금 내역을 자동으로 분석하여 수익률(XIRR) 계산에 반영합니다.
            </p>

            {!result ? (
                <div className="space-y-4">
                    <div
                        onClick={() => fileInputRef.current?.click()}
                        className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer transition-colors ${file ? 'border-blue-200 bg-blue-50' : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50'
                            }`}
                    >
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleFileChange}
                            className="hidden"
                            accept=".xlsx"
                        />
                        {file ? (
                            <div className="text-center">
                                <CheckCircle2 className="text-blue-500 mx-auto mb-2" size={32} />
                                <span className="text-sm font-medium text-slate-700 block truncate max-w-[200px]">
                                    {file.name}
                                </span>
                                <span className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB</span>
                            </div>
                        ) : (
                            <div className="text-center">
                                <Upload className="text-slate-300 mx-auto mb-2" size={32} />
                                <span className="text-sm text-slate-600">파일을 클릭하거나 드래그하여 선택</span>
                                <span className="text-xs text-slate-400 block mt-1">지원: 삼성증권 (.xlsx)</span>
                            </div>
                        )}
                    </div>

                    {error && (
                        <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm flex items-start gap-2">
                            <AlertCircle size={18} className="shrink-0 mt-0.5" />
                            <span>{error}</span>
                        </div>
                    )}

                    <button
                        onClick={handleUpload}
                        disabled={!file || loading}
                        className={`w-full py-3 rounded-xl font-bold flex items-center justify-center gap-2 transition-all ${!file || loading
                            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                            : 'bg-blue-600 text-white hover:bg-blue-700 shadow-md hover:shadow-lg active:scale-[0.98]'
                            }`}
                    >
                        {loading ? (
                            <>
                                <Loader2 className="animate-spin" size={20} />
                                동기화 중...
                            </>
                        ) : (
                            '내역 동기화 시작'
                        )}
                    </button>
                </div>
            ) : (
                <div className="text-center py-4">
                    <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <CheckCircle2 className="text-green-600" size={32} />
                    </div>
                    <h3 className="text-lg font-bold text-slate-800 mb-2">동기화가 완료되었습니다!</h3>

                    <div className="grid grid-cols-2 gap-4 mt-6">
                        <div className="bg-slate-50 p-4 rounded-xl">
                            <span className="text-2xl font-bold text-blue-600">{result.added}</span>
                            <span className="text-xs text-slate-500 block">새로운 내역 추가</span>
                        </div>
                        <div className="bg-slate-50 p-4 rounded-xl">
                            <span className="text-2xl font-bold text-slate-400">{result.skipped}</span>
                            <span className="text-xs text-slate-500 block">중복 내역 건너뜀</span>
                        </div>
                    </div>

                    <button
                        onClick={reset}
                        className="mt-8 text-sm text-slate-500 hover:text-blue-600 font-medium"
                    >
                        다른 파일 추가 업로드
                    </button>
                </div>
            )}

            {!result && (
                <div className="mt-6 pt-6 border-t border-slate-100">
                    <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">도움말</h4>
                    <ul className="text-xs text-slate-500 space-y-1 list-disc list-inside">
                        <li>삼성증권 MTS/HTS에서 '거래내역' 엑셀을 저장하세요.</li>
                        <li>파일명에 '삼성'이 포함되어 있어야 합니다.</li>
                        <li>이미 동기화된 내역은 중복으로 들어가지 않으니 안심하세요.</li>
                    </ul>
                </div>
            )}
        </div>
    );
};
