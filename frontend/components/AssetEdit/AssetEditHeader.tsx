
import React from 'react';
import { X, Wallet, Home, Tag } from 'lucide-react';

interface AssetEditHeaderProps {
    isCash: boolean;
    isRealEstate: boolean;
    assetName: string;
    onClose: () => void;
}

export const AssetEditHeader: React.FC<AssetEditHeaderProps> = ({
    isCash,
    isRealEstate,
    assetName,
    onClose,
}) => {
    return (
        <div className="relative bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 p-6 text-white overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16"></div>
            <div className="absolute bottom-0 left-0 w-24 h-24 bg-white/10 rounded-full -ml-12 -mb-12"></div>

            <div className="relative flex justify-between items-start">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-white/20 backdrop-blur-sm rounded-xl">
                        {isCash ? <Wallet size={24} /> : isRealEstate ? <Home size={24} /> : <Tag size={24} />}
                    </div>
                    <div>
                        <h3 className="text-xl font-bold">
                            {isCash ? '잔액 수정' : isRealEstate ? '시세 수정' : '자산 정보 수정'}
                        </h3>
                        <p className="text-sm text-indigo-100 mt-0.5">{assetName}</p>
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
    );
};
