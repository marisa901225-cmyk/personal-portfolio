/**
 * Settings Page
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { SettingsPanel } from '@components/SettingsPanel';
import { useSettings } from '@hooks/useSettings';

export const SettingsPage: React.FC = () => {
    const { settings, setSettings, saveSettingsToServer } = useSettings();
    const navigate = useNavigate();

    return (
        <SettingsPanel
            settings={settings}
            onSettingsChange={setSettings}
            onBackToDashboard={() => {
                void saveSettingsToServer(settings);
                navigate('/dashboard');
            }}
        />
    );
};

export default SettingsPage;
