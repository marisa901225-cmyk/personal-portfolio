import { useRef, useState, useCallback } from 'react';
import { Asset, AssetCategory } from '../types';
import type { ImportedAssetSnapshot } from './portfolioTypes';
import { validateImportedAssetSnapshotList } from './portfolioBackupValidation';
import { alertError } from '../errors';

interface UseAssetExportOptions {
    onRestoreFromBackup?: (snapshot: ImportedAssetSnapshot[]) => Promise<void>;
}

interface UseAssetExportResult {
    fileInputRef: React.RefObject<HTMLInputElement | null>;
    isRestoring: boolean;
    handleRestoreFromExcelClick: () => void;
    handleRestoreFileChange: React.ChangeEventHandler<HTMLInputElement>;
    handleDownloadExcel: (assets: Asset[]) => void;
}

const parseCsvLine = (line: string): string[] => {
    const result: string[] = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];

        if (inQuotes) {
            if (ch === '"') {
                const next = line[i + 1];
                if (next === '"') {
                    current += '"';
                    i += 1;
                } else {
                    inQuotes = false;
                }
            } else {
                current += ch;
            }
        } else if (ch === '"') {
            inQuotes = true;
        } else if (ch === ',') {
            result.push(current);
            current = '';
        } else {
            current += ch;
        }
    }

    result.push(current);
    return result.map((v) => v.replace(/\r$/, ''));
};

export const useAssetExport = ({
    onRestoreFromBackup,
}: UseAssetExportOptions): UseAssetExportResult => {
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const [isRestoring, setIsRestoring] = useState(false);

    const handleRestoreFromExcelClick = useCallback(() => {
        if (!onRestoreFromBackup) {
            alert('복원 기능이 활성화되어 있지 않습니다.');
            return;
        }
        fileInputRef.current?.click();
    }, [onRestoreFromBackup]);

    const handleRestoreFileChange: React.ChangeEventHandler<HTMLInputElement> = useCallback(
        async (event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (!file) return;
            if (!onRestoreFromBackup) return;

            try {
                setIsRestoring(true);
                const text = await file.text();
                const cleaned = text.replace(/^\uFEFF/, '');
                const lines = cleaned
                    .split(/\n/)
                    .map((line) => line.trim())
                    .filter((line) => line.length > 0);

                if (lines.length < 2) {
                    alert('엑셀 파일에서 데이터 행을 찾을 수 없습니다.');
                    return;
                }

                const header = parseCsvLine(lines[0]).map((h) => h.trim());
                if (!header.includes('자산명') || !header.includes('카테고리')) {
                    alert('이 포트폴리오에서 내보낸 형식의 엑셀 파일이 아닙니다.');
                    return;
                }

                const dataLines = lines.slice(1);
                const snapshot: ImportedAssetSnapshot[] = [];

                dataLines.forEach((rawLine) => {
                    const cols = parseCsvLine(rawLine);
                    if (cols.length < 6) {
                        return;
                    }

                    const name = cols[0]?.trim();
                    const ticker = cols[1]?.trim() || undefined;
                    const categoryRaw = cols[2]?.trim() as AssetCategory | undefined;
                    const amount = Number(cols[3]);
                    const purchasePrice = Number(cols[4]);
                    const currentPrice = Number(cols[5]);
                    const realizedProfit = cols[7] != null ? Number(cols[7]) : undefined;

                    if (!name || !categoryRaw || Number.isNaN(amount) || amount <= 0 || Number.isNaN(currentPrice)) {
                        return;
                    }

                    const category: AssetCategory = categoryRaw;
                    const currency: 'KRW' | 'USD' =
                        category === AssetCategory.STOCK_US ? 'USD' : 'KRW';

                    snapshot.push({
                        name,
                        ticker,
                        category,
                        amount,
                        purchasePrice: Number.isNaN(purchasePrice) ? undefined : purchasePrice,
                        currentPrice,
                        realizedProfit: realizedProfit != null && !Number.isNaN(realizedProfit) ? realizedProfit : undefined,
                        currency,
                    });
                });

                if (snapshot.length === 0) {
                    alert('엑셀 파일에서 유효한 자산 데이터를 찾지 못했습니다.');
                    return;
                }

                const validation = validateImportedAssetSnapshotList(snapshot);
                if (validation.errors.length > 0) {
                    alert(
                        `엑셀 백업 데이터에 문제가 있어 복원을 중단했습니다.\n\n${validation.errors.slice(0, 8).join('\n')}`,
                    );
                    return;
                }

                if (validation.warnings.length > 0 && typeof window !== 'undefined') {
                    const proceed = window.confirm(
                        `엑셀 백업 데이터에 경고가 있습니다.\n그래도 복원할까요?\n\n${validation.warnings.slice(0, 8).join('\n')}`,
                    );
                    if (!proceed) {
                        return;
                    }
                }

                await onRestoreFromBackup(validation.valid);
            } catch (error) {
                alertError('Restore from Excel error', error, {
                    default: '엑셀 파일을 읽는 중 오류가 발생했습니다.\n파일 형식을 확인해주세요.',
                });
            } finally {
                setIsRestoring(false);
            }
        },
        [onRestoreFromBackup],
    );

    const handleDownloadExcel = useCallback((assets: Asset[]) => {
        // Excel requires BOM (\uFEFF) for correct Korean character encoding
        const BOM = '\uFEFF';
        const headers = ['자산명', '티커', '카테고리', '수량', '매수평균가', '현재가', '평가금액', '실현손익', '수익률(%)'];

        const csvRows = assets.map((asset) => {
            const profitRate = asset.purchasePrice
                ? ((asset.currentPrice - asset.purchasePrice) / asset.purchasePrice) * 100
                : 0;

            const safeName = asset.name.replace(/"/g, '""');
            const safeTicker = (asset.ticker || '').replace(/"/g, '""');

            return [
                `"${safeName}"`,
                `"${safeTicker}"`,
                asset.category,
                asset.amount,
                asset.purchasePrice || 0,
                asset.currentPrice,
                asset.amount * asset.currentPrice,
                asset.realizedProfit || 0,
                profitRate.toFixed(2),
            ].join(',');
        });

        const csvString = BOM + [headers.join(','), ...csvRows].join('\n');
        const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');

        // Format date for filename: YYYYMMDD
        const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        link.setAttribute('href', url);
        link.setAttribute('download', `portfolio_backup_${dateStr}.csv`);

        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }, []);

    return {
        fileInputRef,
        isRestoring,
        handleRestoreFromExcelClick,
        handleRestoreFileChange,
        handleDownloadExcel,
    };
};
