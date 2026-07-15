import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.js'],
    globals: true,
    css: true,
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
        // 600000→1800000(30분): 대형 SwUDS(53MB) 첫 impact 분석 파싱 ~400s+ 헤드룸.
        // nginx.conf proxy_read/send_timeout(prod)과 lockstep. 2회차는 캐시로 즉시.
        timeout: 1800000,
        proxyTimeout: 1800000,
      },
      '/download': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
    },
  },
});
