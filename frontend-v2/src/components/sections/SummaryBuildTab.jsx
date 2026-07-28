import { SummaryToolStrip } from './SummaryPanel.jsx';
import BaselineDiffPanel from './BaselineDiffPanel.jsx';
import BuildChangeMatrixPanel from './BuildChangeMatrixPanel.jsx';

/**
 * 빌드 변경 서브탭 — 베이스라인 대비 소스 변화(영향분석 실행 이력과 무관).
 *
 * ⚠ 위계: 맨 위 "과거 빌드 가져오기"는 **설정이지 측정 결과가 아니다**. 예전엔 데이터 패널과
 *   똑같은 `.panel` 카드였고, 그래서 카드 3장이 전부 같은 무게로 보였다 → 여기서는 테두리·
 *   배경 없는 L2 도구 스트립(`SummaryToolStrip`)으로 낮춘다. 라벨·체크박스 DOM은 그대로다.
 */
export default function SummaryBuildTab({
  jobUrl, cacheRoot, srcBuilds, srcBuildsError, allBuilds,
  baselineBuild, diffTarget, onChangeBaseline, onChangeTarget, deltaByBuild, prqaTrendError,
  backfill, backfillBusy, startBackfill, unpinnedCount,
  pinSource, setPinSource, warmMatrix, setWarmMatrix, backfillCount, setBackfillCount,
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      <SummaryToolStrip>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
          {/* ⚠ 조회 실패를 '0개'나 '—'로 위장하지 않는다 — 아래 두 패널이 통째로 비는 원인이라
              사유가 없으면 사용자가 "빌드가 없는 것"으로 읽는다. */}
          <span style={srcBuildsError ? { color: 'var(--color-warning)' } : undefined}>
            {srcBuildsError
              ? `⚠ 캐시 빌드 목록 조회 실패 — ${srcBuildsError}`
              : <>
                  비교 가능한 캐시 빌드 {srcBuilds ? srcBuilds.length : '—'}개
                  {Array.isArray(allBuilds) && allBuilds.length > 0 && ` · Jenkins 빌드 ${allBuilds.length}개 중 소스 스냅샷 보유분만 비교 대상`}
                </>}
          </span>
          {backfillBusy && (
            <span style={{ color: 'var(--color-info)' }}>
              {backfill.phase === 'matrix'
                ? `비교 캐시 계산 중 ${(backfill.matrix?.completed ?? 0) + 1}/${backfill.matrix?.total ?? '?'}${backfill.matrix?.current_build ? ` (#${backfill.matrix.current_build})` : ''}…`
                : `빌드 가져오는 중 ${backfill.completed}/${backfill.total}${backfill.current_build ? ` (#${backfill.current_build})` : ''}…`}
            </span>
          )}
          <button type="button" onClick={startBackfill} disabled={backfillBusy || !jobUrl}
            title={`Jenkins에서 최근 ${backfillCount}개 빌드를 캐시로 가져옵니다. 스냅샷 고정을 켜면 이미 캐시됐어도 HEAD로 받은 빌드는 다시 받아옵니다.`}
            style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: backfillBusy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
            과거 빌드 가져오기
          </button>
        </div>

        {/* 가져오기 옵션 — 기본 ON. 끄면 과거 빌드가 전부 '받아온 날의 트리'가 되어 비교가 무의미해진다.
            ⚠ flex+wrap 이면 폭에 따라 임의 지점에서 접히고 항목 길이가 제각각이라 2줄이 될 때 좌측이
            어긋난다. 균등 폭 grid(auto-fit)로 두면 몇 줄로 접히든 열이 맞는다. 라벨 자체의 중간
            줄바꿈은 nowrap 으로 막는다(체크박스와 텍스트가 세로로 벌어지는 원인). */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(var(--backfill-opt-col, 250px), 1fr))',
          alignItems: 'center', gap: 'var(--sp-1) var(--sp-2)',
        }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', whiteSpace: 'nowrap' }}
            title="각 빌드의 소스를 그 빌드 시각의 SVN revision으로 체크아웃합니다. 끄면 지금 시점의 HEAD를 받아와 모든 빌드가 같은 트리가 됩니다.">
            <input type="checkbox" checked={pinSource} disabled={backfillBusy}
              onChange={(e) => setPinSource(e.target.checked)} />
            스냅샷을 빌드 시점 revision으로 고정
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', whiteSpace: 'nowrap' }}
            title="가져오기가 끝나면 아래 표의 함수 축(변경 함수·ASIL)까지 미리 계산해 둡니다.">
            <input type="checkbox" checked={warmMatrix} disabled={backfillBusy}
              onChange={(e) => setWarmMatrix(e.target.checked)} />
            비교 캐시(함수 축) 자동 생성
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
            가져올 빌드
            <select value={backfillCount} disabled={backfillBusy}
              onChange={(e) => setBackfillCount(Number(e.target.value))}
              style={{ fontSize: 'var(--text-xs)', padding: '1px 4px' }}>
              {[5, 10, 20, 30].map((n) => <option key={n} value={n}>{n}개</option>)}
            </select>
          </label>
          {warmMatrix && (
            /* 항목이 아니라 부연 — 전체 폭을 차지해 위 3개의 열 정렬을 흔들지 않는다 */
            <span style={{ gridColumn: '1 / -1' }}>
              비교 기준 {baselineBuild ? `#${baselineBuild}` : '(자동)'} — 아래 “베이스라인 → 최신 변화”에서 변경
            </span>
          )}
        </div>

        {/* 고정 안 된 스냅샷 경고 — '변화 0'을 코드 미변경으로 오독하지 않게 */}
        {unpinnedCount > 0 && (
          <div style={{ color: 'var(--color-warning)' }}>
            ⚠ 캐시 빌드 {unpinnedCount}개는 소스가 <b>빌드 시점으로 고정되지 않았습니다</b> — 받아온 날의 HEAD 트리라
            서로 같은 소스가 되어 아래 표에서 변화가 0으로 보입니다. 위 “스냅샷 고정”을 켠 채 다시 가져오면 재수집됩니다.
          </div>
        )}
      </SummaryToolStrip>

      {/* 베이스라인 → 최신 변화 — 소스 스냅샷 직접 비교(영향분석 이력 비의존) */}
      <BaselineDiffPanel jobUrl={jobUrl} cacheRoot={cacheRoot}
        builds={srcBuilds} baseline={baselineBuild} target={diffTarget}
        onChangeBaseline={onChangeBaseline} onChangeTarget={onChangeTarget} />

      {/* 빌드별 변경 영향 — 위 패널과 같은 베이스라인을 기준으로 각 빌드의 누적 변화 */}
      <BuildChangeMatrixPanel jobUrl={jobUrl} cacheRoot={cacheRoot}
        baseline={baselineBuild} deltaByBuild={deltaByBuild} prqaTrendError={prqaTrendError} />
    </div>
  );
}
