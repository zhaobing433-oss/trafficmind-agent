import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const isQiantangDemo = env.VITE_RUNTIME_PROFILE === 'qiantang-demo';
  if (isQiantangDemo && !env.VITE_PROXY_TARGET) {
    throw new Error('Qiantang demo requires an explicit VITE_PROXY_TARGET');
  }
  // Default development uses 8000. The demo launcher always supplies its isolated backend explicitly.
  const target = env.VITE_PROXY_TARGET || 'http://localhost:8000';
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('/node_modules/react/') || id.includes('/node_modules/react-dom/') || id.includes('/node_modules/scheduler/')) return 'react-vendor';
            if (id.includes('/node_modules/antd/') || id.includes('/node_modules/@ant-design/')) return 'antd-vendor';
            if (id.includes('/node_modules/echarts') || id.includes('/node_modules/zrender/')) return 'charts-vendor';
            if (id.includes('/node_modules/maplibre-gl/') || id.includes('/node_modules/@maplibre/')) return 'map-vendor';
            return undefined;
          },
        },
      },
    },
  };
});
