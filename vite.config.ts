import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(() => {
  return {
    server: {
      port: 3000,
      host: '0.0.0.0',
    },
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            // React 관련
            'vendor-react': ['react', 'react-dom'],
            // 차트 라이브러리
            'vendor-charts': ['recharts'],
            // 아이콘
            'vendor-icons': ['lucide-react'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./test/setup.ts'],
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
        // 기존 컴포넌트 경로 호환성 유지
        '@components': path.resolve(__dirname, 'components'),
        '@hooks': path.resolve(__dirname, 'hooks'),
        '@lib': path.resolve(__dirname, 'lib'),
      },
    },
  };
});
