/**
 * 정적분석(SCM) 응답 정규화 헬퍼.
 *
 * `AnalysisSection.jsx` 안에 있던 것을 옮겼다 — 컴포넌트 파일이 컴포넌트 아닌 것을
 * export 하면 Fast Refresh 가 동작하지 않는다(react-refresh/only-export-components).
 * 로직은 그대로이고 호출처(컴포넌트·테스트)만 이 경로를 본다.
 */

/**
 * 도구별 정적분석 결과를 **모듈 배열**로 정규화한다.
 *
 * 백엔드 응답: `sa[tool] = {ok, modules:[{label, module_folder, source, ...}]}`.
 * ⚠ 하위호환 — `modules` 배열이 없는 구 응답은 단일 객체를 1-모듈로 취급한다.
 *   `ok:false` 면 빈 배열(표시할 모듈 없음)이다.
 */
export function saModules(tool) {
  if (!tool) return [];
  if (Array.isArray(tool.modules)) return tool.modules;
  return tool.ok ? [tool] : [];
}
