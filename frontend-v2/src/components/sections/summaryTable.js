/**
 * '프로젝트 분석' 탭 계열의 **표·그림 공통 서식**.
 *
 * 왜 만들었나: 패널마다 `th`/`td` 를 각자 정의해 놓아 세 가지가 어긋나 있었다.
 *   ① **본문이 10px(--text-xs)** — 라벨과 데이터가 같은 크기라 표가 글 덩어리로 보였다
 *   ② **숫자가 좌측 정렬 + 가변폭 숫자** — 자릿수가 안 맞아 열이 들쭉날쭉했다
 *   ③ **일부 표만 nowrap** — 함수명·파일 경로가 두세 줄로 접히며 행 높이가 제각각이 됐다
 *      (`ArchitectureImprovementPanel` 의 td 에는 nowrap 자체가 없었다)
 *
 * 규약:
 *   - 헤더 10px muted / **본문 11px** — 위계를 크기로 준다
 *   - 숫자 열은 `numTd`: 우측 정렬 + `tabular-nums` (자릿수가 세로로 맞는다)
 *   - 식별자 열은 `nameTd(max)`: 줄바꿈 대신 **말줄임** + `title` 로 전체값 (행 높이 균일)
 *   - 표는 항상 `SCROLL` 로 감싼다 — 좁은 폭에서 잘리는 대신 가로 스크롤
 */

/** 표 자체. `width:100%` + collapse. */
export const TABLE = { borderCollapse: 'collapse', width: '100%' };

/** 표를 감싸는 스크롤 컨테이너 — 좁은 폭에서 셀이 잘리지 않게. */
export const SCROLL = { overflowX: 'auto' };

/** 헤더 셀 — 10px muted, 줄바꿈 없음. */
export const th = {
  fontSize: 'var(--text-xs)', fontWeight: 600, textAlign: 'left',
  padding: '4px 8px', color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
};

/** 본문 셀 — 11px. 줄바꿈 없음(행 높이 균일). */
export const td = {
  fontSize: 'var(--text-sm)', padding: '4px 8px',
  borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
};

/** 숫자 헤더 — 본문이 우측 정렬이므로 헤더도 맞춘다. */
export const numTh = { ...th, textAlign: 'right' };

/**
 * 숫자 셀 — 우측 정렬 + 고정폭 숫자.
 * `tabular-nums` 가 없으면 1 과 8 의 폭이 달라 열이 미세하게 흔들린다.
 */
export const numTd = { ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' };

/**
 * 식별자 셀(함수명·파일 경로) — 길면 말줄임. **반드시 `title` 을 함께 줄 것**(전체값 확인 수단).
 *
 * ⚠ `table-layout: auto` 에서 셀의 `max-width` 는 스펙상 강제가 아니라 힌트다. Chromium 계열은
 *   `overflow:hidden` 과 함께 주면 대체로 지켜 말줄임이 되지만, 안 지켜지더라도 `nowrap` 덕에
 *   **줄바꿈은 나지 않고** 표가 넓어져 `SCROLL` 로 가로 스크롤될 뿐이다 — 어느 쪽이든
 *   "행 높이가 제각각"이 되는 원래 문제는 생기지 않는다.
 * @param {number} max 최대 폭(px)
 */
export function nameTd(max = 220) {
  return { ...td, maxWidth: max, overflow: 'hidden', textOverflow: 'ellipsis' };
}

/** 문장이 들어가는 셀(근거·조치) — 여기만 줄바꿈을 허용하되 폭을 묶는다. */
export function textTd(max = 320) {
  return { ...td, whiteSpace: 'normal', maxWidth: max, lineHeight: 1.45 };
}

/**
 * 그림/블록 제목 — 2열 그리드에서 각 칸이 "제목 있는 한 덩어리"로 읽히게 한다.
 *
 * 예전엔 다이어그램 제목이 각주와 **똑같은 10px muted** 라, 여러 그림을 나란히 놓으면
 * 어디까지가 한 그림인지 눈이 못 잡았다. 제목은 본문색 11px/600, 각주는 10px muted 로 가른다.
 */
export const figTitle = {
  fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text)', marginBottom: 4,
};

/** 각주·한계 고지 — 항상 10px muted. 제목과 같은 크기가 되면 위계가 무너진다. */
export const note = { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' };
