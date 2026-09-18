/**
 * '프로젝트 분석' 탭(summary) 계열이 공유하는 플래그·포매터.
 *
 * 탭이 서브탭 4개(개요·아키텍처·소스코드·빌드 변경)로 쪼개지면서 `SHOW` 플래그가 세 파일에
 * 흩어지게 됐다. 플래그는 복원 스위치라 **단일 출처**여야 해서 여기로 뺐다.
 * (컴포넌트는 두지 않는다 — .js 라 react-refresh 규칙에 걸리지 않게 유지)
 */

/**
 * 패널 표시 스위치(사용자 결정으로 숨긴 항목) — **코드는 살려 두고 플래그만 false**.
 * 되살리려면 해당 값을 true로. JSX 주석 처리 대신 플래그를 쓰는 이유: 주석 블록은 내부에
 * 닫는 시퀀스가 섞이면 깨지고, 참조가 끊긴 변수·import가 lint 오류로 번져 복원 비용이 커진다.
 * ⚠ traceability를 false로 둬도 trace fetch/자동생성 effect는 유지해야 한다 —
 *   문제점 배너와 AI 인사이트가 trace를 소비하므로, 같이 지우면 배너가 조용히 빈다.
 */
export const SHOW = {
  pipelineHealth: false,
  staticDynamic: false,
  traceability: false,
  testDesign: false,
};

/** 카드 안쪽 패딩 — `.panel` 기본 sp-4 대신 이 탭 계열이 쓰는 sp-3. */
export const PANEL = { padding: 'var(--sp-3)' };

export function fmtInt(n) {
  return (n == null || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString();
}

export function pctOrNull(r) {
  return r == null || Number.isNaN(Number(r)) ? null : Number(r) * 100;
}
