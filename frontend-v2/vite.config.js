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
    // 84파일을 병렬 워커로 돌리는 스위트다(환경 준비만 570초). 기본 testTimeout 5,000ms 는
    // 여러 번의 렌더-플러시를 순서대로 기다리는 테스트에서 **부하에 따라** 넘는다 —
    // 그러면 같은 트리가 실행마다 통과/실패한다(게이트 비결정, 회귀와 구별 불가).
    // 실측 2026-09-02: DocGenStatusBoard 응답 역전 이 HEAD 에서 2회 중 1회 실패(5,956ms).
    // 통과하는 테스트는 느려지지 않는다 — 이건 **실패 확정까지의 상한**이다.
    // vitest.setup.js 의 asyncUtilTimeout(5,000) 보다 반드시 커야 한다. 안 그러면 개별
    // 대기가 끝나기 전에 테스트 자체가 먼저 죽어 원인이 가려진다(실측: 그 순서로 겪었다).
    testTimeout: 20000,
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
