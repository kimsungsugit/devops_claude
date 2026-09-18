/**
 * 완료된 산출물의 **저장 경로**를 진행(progress) payload 에서 뽑는다.
 *
 * ⚠ 문서마다 shape 가 다르다. STS/SUTS/SITS 는 진행 dict 자체에 `output_path` 를 싣지만
 *   (`backend/routers/local.py:2372` 등), **UDS 는 `result.path`** 다(`local.py:1660`).
 *   그래서 예전의 `progress?.output_path || progress?.xlsm_path` 는 UDS 에서 늘 빈 값이었고,
 *   경로가 분명히 있는데도 화면은 "모른다" 고 말하게 된다.
 *
 * 못 찾으면 **빈 문자열**을 준다 — 추측한 경로를 보여주면 없는 파일을 열러 가게 된다.
 *
 * (컴포넌트 파일이 아닌 별도 모듈에 두는 이유: `react-refresh/only-export-components`.)
 */
export function extractOutputPath(progress) {
  const r = progress?.result;
  const cands = [
    progress?.output_path, progress?.xlsm_path, progress?.path,
    r?.output_path, r?.xlsm_path, r?.path,
  ];
  for (const c of cands) {
    if (typeof c === 'string' && c.trim()) return c.trim();
  }
  return '';
}
