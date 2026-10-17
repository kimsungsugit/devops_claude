import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import { defineConfig, globalIgnores } from 'eslint/config';

/**
 * frontend-v2 ESLint flat config (ESLint 9).
 *
 * 이 파일이 없는 동안 PostToolUse 훅의 `npx eslint` 가 매 편집마다 ERROR 만 냈다
 * — JSX lint 게이트가 한 번도 동작한 적이 없었다는 뜻이다. 구성은 `_archive/frontend/`
 * (같은 저장소의 구 프론트엔드, React 19 + Vite 로 실제 돌던 설정)를 베이스로 하고
 * 이 트리에 맞춰 두 곳을 조정했다 — 아래 (A)(B).
 */
export default defineConfig([
  // 번들 산출물. 안 막으면 dist/assets/index-*.js 하나로 위반이 폭주한다.
  globalIgnores(['dist', 'coverage', 'node_modules']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // (A) archive 의 varsIgnorePattern 은 **vars** 패턴이라 catch 파라미터엔 안 걸린다.
      // ESLint 9 는 caughtErrors:"all" 이 기본이므로, 이 저장소에 30곳 있는
      // `catch (_) { /* ignore */ }` 관용구가 전부 error 가 된다. 의도적 무시임을
      // 밑줄 접두사로 표시하는 관행을 그대로 인정한다.
      // (B) `const { token, ...rest } = cfg` — **빼고 나머지를 쓰는** 관용구.
      // JS 에 이걸 달리 쓸 방법이 없다(`delete` 는 원본을 바꾼다). 이름을 `_token` 으로
      // 바꾸는 건 **틀린 수정**이다 — 그러면 `token` 이 `rest` 에 남아 localStorage 에
      // 저장된다. 즉 이 위반은 코드 결함이 아니라 **설정 구멍**이었다.
      // 실측: `api.js:278` 이 정확히 이 형태다(Jenkins 토큰을 저장 전에 떼어낸다).
      'no-unused-vars': ['error', {
        varsIgnorePattern: '^[A-Z_]',
        args: 'after-used',
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        ignoreRestSiblings: true,
      }],
    },
  },
  {
    // (B) 테스트 파일. vitest 는 vite.config.js 에서 `globals: true` 라 describe/it/expect/vi
    // 를 전역 주입하는데, config 가 그걸 모르면 37개 테스트 파일에서 no-undef 가
    // 2,000건 넘게 터진다 — 코드 부채가 아니라 설정 미비다.
    files: ['**/__tests__/**/*.{js,jsx}', '**/*.test.{js,jsx}', 'vitest.setup.js'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node, ...globals.vitest },
    },
    rules: {
      // 테스트에서 컴포넌트 외 export(픽스처 등)는 정상이다.
      'react-refresh/only-export-components': 'off',
    },
  },
  {
    // Node 컨텍스트에서 도는 설정 파일.
    files: ['vite.config.js', 'eslint.config.js'],
    languageOptions: { globals: globals.node },
  },
]);
