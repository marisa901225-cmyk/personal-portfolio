import React, { useRef } from 'react';
import { AlertCircle, CheckCircle2, Loader2, Upload } from 'lucide-react';
import type { BackendExpenseUploadResult } from '@/shared/api/client';

interface ExpenseUploadPanelProps {
    isRemoteEnabled: boolean;
    isUploading: boolean;
    isLearning: boolean;
    uploadError: string | null;
    uploadResult: BackendExpenseUploadResult | null;
    learnResult: { added: number; updated: number; ai_trained?: boolean } | null;
    onPickFile: () => void;
    onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
    onLearn: () => void;
    onDismissLearnResult: () => void;
    fileInputRef: React.RefObject<HTMLInputElement | null>;
}

export const ExpenseUploadPanel: React.FC<ExpenseUploadPanelProps> = ({
    isRemoteEnabled,
    isUploading,
    isLearning,
    uploadError,
    uploadResult,
    learnResult,
    onPickFile,
    onFileChange,
    onLearn,
    onDismissLearnResult,
    fileInputRef,
}) => {
    return (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">가계부 내역 업로드</h2>
                    <p className="text-sm text-slate-500 mt-1">
                        카드/계좌 내역 파일(.xlsx, .xls, .csv)을 업로드하면 자동으로 분류됩니다.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <input
                        ref={fileInputRef}
                        type="file"
                        onChange={onFileChange}
                        className="hidden"
                        accept=".xlsx,.xls,.csv"
                    />
                    <button
                        type="button"
                        onClick={onPickFile}
                        disabled={!isRemoteEnabled || isUploading}
                        className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors ${!isRemoteEnabled || isUploading
                            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                            : 'bg-indigo-600 text-white hover:bg-indigo-700'
                            }`}
                    >
                        {isUploading ? (
                            <>
                                <Loader2 size={16} className="animate-spin" />
                                업로드 중...
                            </>
                        ) : (
                            <>
                                <Upload size={16} />
                                내역 업로드
                            </>
                        )}
                    </button>
                    <button
                        type="button"
                        onClick={onLearn}
                        disabled={!isRemoteEnabled || isLearning}
                        title="과거 내역을 분석하여 카테고리 분류 규칙을 업데이트합니다."
                        className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors border ${!isRemoteEnabled || isLearning
                            ? 'bg-slate-50 text-slate-300 border-slate-100 cursor-not-allowed'
                            : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                            }`}
                    >
                        {isLearning ? (
                            <>
                                <Loader2 size={16} className="animate-spin" />
                                학습 중...
                            </>
                        ) : (
                            '분류 학습시키기'
                        )}
                    </button>
                </div>
            </div>

            {!isRemoteEnabled && (
                <div className="mt-4 text-sm text-slate-500">
                    서버 URL과 API 비밀번호를 먼저 설정해주세요.
                </div>
            )}

            {uploadError && (
                <div className="mt-4 bg-red-50 text-red-600 p-3 rounded-lg text-sm flex items-start gap-2">
                    <AlertCircle size={18} className="shrink-0 mt-0.5" />
                    <span>{uploadError}</span>
                </div>
            )}

            {uploadResult && (
                <div className="mt-4 bg-emerald-50 text-emerald-700 p-4 rounded-xl">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                        <CheckCircle2 size={18} />
                        업로드 완료
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-3 text-center text-sm">
                        <div className="bg-white/60 rounded-lg py-2">
                            <div className="font-semibold">{uploadResult.total_rows}</div>
                            <div className="text-xs text-emerald-700/80">총 거래</div>
                        </div>
                        <div className="bg-white/60 rounded-lg py-2">
                            <div className="font-semibold">{uploadResult.added}</div>
                            <div className="text-xs text-emerald-700/80">추가</div>
                        </div>
                        <div className="bg-white/60 rounded-lg py-2">
                            <div className="font-semibold">{uploadResult.skipped}</div>
                            <div className="text-xs text-emerald-700/80">중복 제외</div>
                        </div>
                    </div>
                    <div className="mt-2 text-xs text-emerald-700/80">
                        파일: {uploadResult.filename}
                    </div>
                </div>
            )}

            {learnResult && (
                <div className="mt-4 bg-indigo-50 text-indigo-700 p-4 rounded-xl border border-indigo-100">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-sm font-semibold">
                            <CheckCircle2 size={18} />
                            패턴 학습 완료
                        </div>
                        <button
                            onClick={onDismissLearnResult}
                            className="text-xs text-indigo-400 hover:text-indigo-600"
                        >
                            닫기
                        </button>
                    </div>
                    <p className="mt-2 text-[11px] text-indigo-600/80 leading-relaxed">
                        기존 내역을 분석하여 <b>{learnResult.added + learnResult.updated}개</b>의 가맹점 분류 규칙을 확보하고,
                        <b> 전담 분류 AI(Naive Bayes)</b> 모델을 최신 상태로 학습시켰습니다.<br />
                        이제 새로운 내역 업로드 시 훨씬 더 똑똑하게 분류해 줍니다.
                    </p>
                </div>
            )}
        </div>
    );
};
