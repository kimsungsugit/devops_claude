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
        timeout: 600000,
        proxyTimeout: 600000,
      },
      '/download': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      },
    },
  },
});
