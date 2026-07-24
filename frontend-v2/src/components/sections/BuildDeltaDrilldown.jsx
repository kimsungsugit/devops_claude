/**
 * BuildDeltaDrilldown — 빌드 타임라인 행 확장 패널: 빌드간 PRQA 위반 delta 드릴다운.
 * POST /api/jenkins/prqa-delta(쌍 단위 on-demand — 서버가 RCR 상세를 빌드별 디스크 캐시)로
 * 규칙 4분류(신규/해소/증감) + 파일별 delta + '변경한 파일의 위반 증가' 신호를 렌더한다.
 *
 * ISO 정직성: available:false는 reason 한국어로 그대로 노출(빈 delta/0 위장 금지),
 * in_changed_set 필드 부재(change-log 없음)는 배지 미표시(false로 위장하지 않음).
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const REASON_KO = {
  build_not_cached: '이 빌드의 분석 캐시가 없습니다',
  no_baseline_build: '비교할 이전 캐시 빌드가 없습니다 (첫 분석 빌드)',
  baseline_not_cached: '지정한 기준 빌드의 캐시가 없습니다',
  baseline_build_number_invalid: '기준 빌드 번호가 올바르지 않습니다',
  no_rcr_current: '이 빌드에 PRQA(RCR) 리포트가 없어 위반 delta를 계산할 수 없습니다',
  no_rcr_baseline: '기준 빌드에 PRQA(RCR) 리포트가 없어 위반 delta를 계산할 수 없습니다',
  job_url_required: 'Jenkins job 정보가 없습니다',
  build_number_required: '빌드 번호가 없습니다',
};

function DeltaNum({ v }) {
  if (v == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = v > 0 ? 'var(--color-danger)' : v < 0 ? 'var(--color-success)' : 'var(--text-muted)';
  return <span style={{ color, fontWeight: 600 }}>{v > 0 ? `+${v}` : v === 0 ? '±0' : v}</span>;
}

function RulePill({ text, color }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: color, marginRight: 4, marginBottom: 3,
    }}>{text}</span>
  );
}

export default function BuildDeltaDrilldown({ jobUrl, cacheRoot, scmId, buildNumber, onOpenImpact }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl || buildNumber == null) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/jenkins/prqa-delta', {
          job_url: jobUrl, cache_root: cacheRoot, build_number: buildNumber, scm_id: scmId || '',
        });
        if (!cancelled) { setData(resp || { available: false, reason: 'empty_response' }); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, scmId, buildNumber]);

  const xs = { fontSize: 'var(--text-xs)' };
  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };

  if (error) {
    return <div style={{ ...xs, color: 'var(--color-danger)', padding: 'var(--sp-2)' }}>위반 delta 조회 오류: {error}</div>;
  }
  if (!data) {
    return <div style={{ ...xs, color: 'var(--text-muted)', padding: 'var(--sp-2)' }}><span className="spinner" /> 위반 delta 계산 중… (첫 조회는 RCR 파싱으로 수 초)</div>;
  }
  if (!data.available) {
    return (
      <div style={{ ...xs, color: 'var(--text-muted)', padding: 'var(--sp-2)' }}>
        {REASON_KO[data.reason] || `위반 delta를 계산할 수 없습니다 (${data.reason || 'unknown'})`}
      </div>
    );
  }

  const rules = data.rules || {};
  const files = Array.isArray(data.files) ? data.files : [];
  const signals = Array.isArray(data.signals) ? data.signals : [];
  const totals = data.totals || {};
  const hasChangedInfo = files.some((f) => 'in_changed_set' in f);

  return (
    <div style={{ padding: 'var(--sp-2) var(--sp-3)', display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)', background: 'var(--bg-elevated, var(--panel))' }}>
      {/* 헤더 — 비교 쌍 + 총계 delta */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <b style={xs}>PRQA 위반 delta</b>
        <span style={xs}>#{data.baseline_build_number}{data.baseline_auto ? '(직전)' : ''} → #{data.build_number}</span>
        <span style={xs}>
          총 위반 {totals.base ?? '—'} → {totals.cur ?? '—'} (<DeltaNum v={totals.delta} />)
        </span>
        {onOpenImpact && (
          <button type="button" onClick={onOpenImpact}
            style={{ ...xs, marginLeft: 'auto', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            변경 영향 평가에서 열기
          </button>
        )}
      </div>

      {/* 변경 파일 신호 문장 */}
      {signals.length > 0 && (
        <div style={{ ...xs, color: 'var(--color-danger)' }}>
          ⚠ 이 빌드에서 변경한 파일 {signals.length}개의 위반이 늘었습니다 — {signals.slice(0, 3).map((s) => `${String(s.file).split('/').pop()} +${s.delta}${s.rules?.length ? ` (${s.rules.join(', ')})` : ''}`).join(' · ')}
        </div>
      )}

      {/* 규칙 delta */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-4)' }}>
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 3 }}>신규 위반 규칙 {rules.new?.length || 0}</div>
          <div>{(rules.new || []).slice(0, 8).map((r) => <RulePill key={r.rule} text={`${r.rule} +${r.count}`} color="var(--color-danger)" />)}
            {(rules.new || []).length === 0 && <span style={{ ...xs, color: 'var(--text-muted)' }}>없음</span>}</div>
        </div>
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 3 }}>해소된 규칙 {rules.resolved?.length || 0}</div>
          <div>{(rules.resolved || []).slice(0, 8).map((r) => <RulePill key={r.rule} text={`${r.rule} −${r.count_was}`} color="var(--color-success)" />)}
            {(rules.resolved || []).length === 0 && <span style={{ ...xs, color: 'var(--text-muted)' }}>없음</span>}</div>
        </div>
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 3 }}>증감 규칙</div>
          <div style={xs}>
            {[...(rules.increased || []).slice(0, 5), ...(rules.decreased || []).slice(0, 5)].map((r) => (
              <div key={r.rule}>{r.rule}: {r.base}→{r.cur} (<DeltaNum v={r.delta} />)</div>
            ))}
            {(rules.increased || []).length === 0 && (rules.decreased || []).length === 0 && <span style={{ color: 'var(--text-muted)' }}>없음</span>}
          </div>
        </div>
      </div>
      {(rules.residual_delta || 0) !== 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          * 규칙 미귀속(기타 비상위) 위반 변화 <DeltaNum v={rules.residual_delta} /> — WorstRules 상위 규칙 밖 몫이라 규칙별 분해 불가
        </div>
      )}

      {/* 파일별 delta */}
      {files.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr>
                <th style={th}>파일</th><th style={th}>기준</th><th style={th}>현재</th><th style={th}>Δ</th>
                <th style={th}>주요 규칙 변화</th>{hasChangedInfo && <th style={th}>변경</th>}
              </tr>
            </thead>
            <tbody>
              {files.slice(0, 20).map((f) => (
                <tr key={f.path || f.file}>
                  <td style={td} title={f.path || f.file}>{f.file}</td>
                  <td style={td}>{f.base}</td>
                  <td style={td}>{f.cur}</td>
                  <td style={td}><DeltaNum v={f.delta} /></td>
                  <td style={{ ...td, whiteSpace: 'normal' }}>
                    {(() => {
                      // deep-review W-B/W1: '기타 ±N' = 파일 Δ − Σ(표시된 top-3 규칙) — WorstRules
                      // 미귀속 잔차뿐 아니라 4위+ 규칙까지 흡수해 `표시 + 기타 == Δ`가 항상 성립
                      // (전체 규칙으로 합산하면 4위+ 규칙이 표시에도 기타에도 없이 침묵 소멸).
                      const shown = (f.rules || []).slice(0, 3);
                      const parts = shown.map((r) => `${r.rule} ${r.delta > 0 ? '+' : ''}${r.delta}`);
                      const ruleSum = shown.reduce((s, r) => s + (r.delta || 0), 0);
                      const residual = (f.delta || 0) - ruleSum;
                      if (residual !== 0) parts.push(`기타 ${residual > 0 ? '+' : ''}${residual}`);
                      return parts.join(', ') || '—';
                    })()}
                  </td>
                  {hasChangedInfo && (
                    <td style={td}>{f.in_changed_set ? <RulePill text="변경파일" color="var(--color-info)" /> : ''}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {(files.length > 20 || (data.files_omitted || 0) > 0) && (
            <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>
              표시 {Math.min(files.length, 20)}개 / delta 파일 {files.length + (data.files_omitted || 0)}개
            </div>
          )}
        </div>
      )}
      {files.length === 0 && <div style={{ ...xs, color: 'var(--text-muted)' }}>파일 단위 위반 변화가 없습니다.</div>}

      {(data.truncation?.cur_files_truncated_to || data.truncation?.base_files_truncated_to) && (
        <div style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 일부 빌드의 위반 상세가 절단되어 delta가 불완전할 수 있습니다.</div>
      )}
    </div>
  );
}
