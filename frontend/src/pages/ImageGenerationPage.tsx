import React from 'react';
import { ImageGenerationDashboard } from '@components/ImageGeneration/ImageGenerationDashboard';
import { useSettings } from '@hooks/useSettings';

export const ImageGenerationPage: React.FC = () => {
  const { settings } = useSettings();

  return (
    <ImageGenerationDashboard
      serverUrl={settings.serverUrl}
      apiToken={settings.apiToken}
      cookieAuth={settings.cookieAuth}
    />
  );
};

export default ImageGenerationPage;
