/**
 * Add Asset Page
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AddAssetForm } from '@components/AddAssetForm';
import { useApiClient } from '@/shared/api/apiClient';
import { useCreateAsset } from '@/shared/api/mutations';
import { useSettings } from '@hooks/useSettings';
import { Asset } from '@lib/types';

export const AddAssetPage: React.FC = () => {
    const { settings } = useSettings();
    const navigate = useNavigate();
    const apiClient = useApiClient({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
    });

    const createAssetMutation = useCreateAsset(apiClient);

    const handleSave = async (newAsset: Asset) => {
        await createAssetMutation.mutateAsync({
            name: newAsset.name,
            ticker: newAsset.ticker,
            category: newAsset.category,
            currency: newAsset.currency,
            amount: newAsset.amount,
            current_price: newAsset.currentPrice,
            purchase_price: newAsset.purchasePrice,
            realized_profit: newAsset.realizedProfit ?? 0,
            index_group: newAsset.indexGroup,
            cma_config: newAsset.cmaConfig
                ? {
                    principal: newAsset.cmaConfig.principal,
                    annual_rate: newAsset.cmaConfig.annualRate,
                    tax_rate: newAsset.cmaConfig.taxRate,
                    start_date: newAsset.cmaConfig.startDate,
                }
                : null,
        });
        navigate('/assets');
    };

    return (
        <AddAssetForm
            onSave={handleSave}
            onCancel={() => navigate('/dashboard')}
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
        />
    );
};

export default AddAssetPage;
