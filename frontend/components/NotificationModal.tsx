import React from 'react';
import { CheckCircle, X } from 'lucide-react';

interface NotificationModalProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    message: string;
}

export const NotificationModal: React.FC<NotificationModalProps> = ({
    isOpen,
    onClose,
    title,
    message,
}) => {
    if (!isOpen) return null;

    return (
        <div
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center px-4 animate-fade-in"
            onMouseDown={onClose}
        >
            <div
                className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all"
                onMouseDown={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="relative bg-gradient-to-br from-emerald-500 via-emerald-600 to-teal-600 p-6 text-white overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
                    <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>

                    <div className="relative flex justify-between items-start">
                        <div className="flex items-center gap-3">
                            <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                                <CheckCircle size={24} />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold">{title}</h3>
                                <p className="text-sm text-emerald-100 mt-0.5">작업이 완료되었습니다</p>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                        >
                            <X size={20} />
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="p-6">
                    <p className="text-slate-700 text-base leading-relaxed">{message}</p>
                </div>

                {/* Footer */}
                <div className="p-6 bg-slate-50 border-t border-slate-200 flex justify-end">
                    <button
                        onClick={onClose}
                        className="px-6 py-2.5 bg-gradient-to-r from-emerald-500 to-teal-600 text-white text-sm font-semibold hover:shadow-lg hover:scale-105 rounded-xl transition-all duration-200"
                    >
                        확인
                    </button>
                </div>
            </div>
        </div>
    );
};
