import { useState, useCallback, useMemo } from 'react';
import { post, api, defaultCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

const CHANGE_TYPE_KO = { BODY: '본문', HEADER: '헤더', SIGNATURE: '시그니처', NEW: '신규', DELETE: '삭제', VARIABLE: '변수' };
const COVERAGE_METRIC_KO = { mcdc: 'MC/DC', branch: '분기', statement: '구문' };

// 함수별 VectorCAST 커버리지 셀 — ASIL 타깃 메트릭 % + 충족 여부 + 직전 대비 Δ.
function renderCoverageCell(cov) {
  if (!cov) return <span className="text-muted">-</span>;
  const cur = cov.current_rate;
  const metricKo = COVERAGE_METRIC_KO[cov.target_metric] || cov.target_metric;
  // 매칭됐으나 타깃 메트릭 미측정(예: 리포트에 MC/DC 컬럼 없음) — 빨강 '미달(실패)'이 아니라
  // 노랑 '미측정(증거 부재)'으로 표시해 false 미달 경보를 막는다.
  if (cov.unmeasured_target) {
    return (
      <span title={`${metricKo} 미측정 — 이 리포트에 ${metricKo} 데이터가 없습니다(증거 부재, 시험 실패 아님). 별도 ${metricKo} 리포트가 필요합니다.`}>
        <span className="pill pill-warning" style={{ fontSize: 9 }}>{metricKo} 미측정</span>
      </span>
    );
  }
  const pct = (typeof cur === 'number') ? `${Math.round(cur * 100)}%` : '—';
  const d = cov.delta;
  let deltaEl = null;
  if (typeof d === 'number' && Math.abs(d) > 1e-9) {
    const down = d < 0;
    deltaEl = (
      <span style={{ color: down ? 'var(--color-danger)' : 'var(--color-success)', marginLeft: 4, fontSize: 9 }}>
        {down ? '▼' : '▲'}{Math.abs(Math.round(d * 100))}
      </span>
    );
  }
  return (
    <span title={`${metricKo} 커버리지 ${pct} (목표 100%)${typeof d === 'number' ? `, 직전 대비 ${(d * 100).toFixed(0)}%p` : ''}`}>
      <span className={`pill ${cov.meets_target ? 'pill-success' : 'pill-danger'}`} style={{ fontSize: 9 }}>
        {metricKo} {pct}
      </span>
      {deltaEl}
    </span>
  );
}

const DOC_STATUS = {
  review_required: { tone: 'warning', label: '검토 필요' },
  completed: { tone: 'success', label: '완료' },
  planned: { tone: 'info', label: '계획됨' },
  skipped: { tone: 'neutral', label: '건너뜀' },
  failed: { tone: 'danger', label: '실패' },
};

export default function ImpactGuideSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const impact = analysisResult?.impactData;
  const [guide, setGuide] = useState(null);
  const [aiGuide, setAiGuide] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedFn, setSelectedFn] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [hopFilter, setHopFilter] = useState('all');
  const [docFilter, setDocFilter] = useState('all');
  const [demoMode, setDemoMode] = useState(false);

  // Impact data from analysis
  const changedFiles = impact?.trigger?.changed_files ?? impact?.changed_files ?? [];
  const changedFunctions = impact?.changed_function_types ?? {};
  const changedFnEntries = Object.entries(changedFunctions);
  const actions = impact?.actions ?? impact?.documents ?? {};
  const linkedDocs = impact?._linked_docs
    ?? analysisResult?.matchedScm?.linked_docs
    ?? analysisResult?.scmList?.[0]?.linked_docs
    ?? {};
  const impactGroups = impact?.impact ?? {};
  // 백엔드 ISO 증거: 함수별 메타(ASIL 등) + 경고(과소보고/cloudium/ASIL escalation 등) + ASIL 요약.
  const functionMeta = impact?.function_meta ?? {};
  const impactWarnings = Array.isArray(impact?.warnings) ? impact.warnings : [];
  const asilInfo = impact?.asil ?? null;
  // MC/DC delta: 영향 함수별 VectorCAST 커버리지(ASIL 타깃 대비 gap + 이력 delta).
  const coverageGap = impact?.coverage_gap ?? null;
  const coverageByFn = useMemo(() => {
    const m = {};
    for (const r of (coverageGap?.functions || [])) { if (r.function) m[r.function] = r; }
    return m;
  }, [coverageGap]);
  // 회귀시험 선정: 영향 함수 → 재실행 대상 SUTS TC / SITS call-chain(ISO 26262 증거).
  const regressionSet = impact?.regression_test_set ?? null;

  // Demo data for testing — simulates real .c file changes
  const demoFunctions = {
    'g_DrvIn_Main': 'BODY',
    'g_DrvIn_MotorSpeed': 'BODY',
    's_MotorSpdCtrl_AutoClose': 'BODY',
    's_MotorSpdCtrl_AutoOpen': 'SIGNATURE',
    's_AntipinchDetect_Close': 'BODY',
    'g_Ap_BuzzerCtrl_Func': 'BODY',
    's_DoorStateCtrl': 'BODY',
    'g_SystemStatusCheck': 'VARIABLE',
  };
  const demoImpact = {
    direct: ['g_DrvIn_Main', 'g_DrvIn_MotorSpeed', 's_MotorSpdCtrl_AutoClose', 's_MotorSpdCtrl_AutoOpen', 's_AntipinchDetect_Close'],
    indirect_1hop: ['g_Ap_BuzzerCtrl_Func', 's_DoorStateCtrl'],
    indirect_2hop: ['g_SystemStatusCheck'],
  };
  const activeFnEntries = demoMode ? Object.entries(demoFunctions) : changedFnEntries;
  const activeImpactGroups = demoMode ? demoImpact : impactGroups;
  const activeChangedFiles = demoMode ? ['DrvIn_Main_PDS.c', 'Ap_MotorCtrl_PDS.c'] : changedFiles;

  const filteredGuide = useMemo(() => {
    if (!guide) return [];
    let items = guide.details;
    if (hopFilter !== 'all') items = items.filter(d => d.hop === hopFilter);
    if (docFilter === 'has_reqs') items = items.filter(d => d.requirements.length > 0);
    else if (docFilter === 'has_sts') items = items.filter(d => d.stsTestCases.length > 0);
    else if (docFilter === 'has_suts') items = items.filter(d => d.sutsTestCases.length > 0);
    else if (docFilter === 'no_mapping') items = items.filter(d => d.requirements.length === 0 && d.stsTestCases.length === 0);
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      items = items.filter(d =>
        d.function.toLowerCase().includes(q) ||
        d.requirements.some(r => r.toLowerCase().includes(q)) ||
        d.stsTestCases.some(tc => tc.toLowerCase().includes(q))
      );
    }
    return items;
  }, [guide, hopFilter, docFilter, searchTerm]);

  // Build detailed guide
  const buildGuide = useCallback(async () => {
    if (!activeFnEntries.length) {
      toast('info', '변경된 함수가 없습니다.');
      return;
    }
    setLoading(true);
    try {
      // 1. UDS func→req mapping
      let udsMapping = [];
      if (linkedDocs.uds) {
        try {
          const d = await post('/api/jenkins/uds/extract-mapping', { uds_path: linkedDocs.uds });
          udsMapping = d?.mapping_pairs ?? [];
        } catch (_) {}
      }

      // 2. STS req→TC mapping
      let stsTCs = [];
      if (linkedDocs.sts) {
        try {
          const d = await post('/api/jenkins/sts/extract-traceability', { path: linkedDocs.sts, doc_type: 'sts' });
          stsTCs = d?.vcast_rows ?? [];
          // N21: 외부 형식 SUTS/STS — 시트 미인식 시 사용자에게 명확 안내
          if (!stsTCs.length && Array.isArray(d?.available_sheets) && typeof toast === 'function') {
            toast('warning', `STS 시트 미인식. 사용 가능한 시트: ${d.available_sheets.join(', ')}`);
          }
        } catch (_) {}
      }

      // 3. SUTS func→TC mapping
      let sutsTCs = [];
      if (linkedDocs.suts) {
        try {
          const d = await post('/api/jenkins/sts/extract-traceability', { path: linkedDocs.suts, doc_type: 'suts' });
          sutsTCs = d?.vcast_rows ?? [];
          if (!sutsTCs.length && Array.isArray(d?.available_sheets) && typeof toast === 'function') {
            toast('warning', `SUTS 시트 미인식. 사용 가능한 시트: ${d.available_sheets.join(', ')}`);
          }
        } catch (_) {}
      }

      // Build per-function guide
      const funcToReqs = {};
      for (const mp of udsMapping) {
        for (const fn of (mp.source_ids || [])) {
          if (!funcToReqs[fn]) funcToReqs[fn] = new Set();
          funcToReqs[fn].add(mp.requirement_id);
        }
      }

      const reqToStsTCs = {};
      for (const row of stsTCs) {
        if (!reqToStsTCs[row.requirement_id]) reqToStsTCs[row.requirement_id] = new Set();
        reqToStsTCs[row.requirement_id].add(row.testcase);
      }

      const fnToSutsTCs = {};
      for (const row of sutsTCs) {
        const fn = row.unit || '';
        if (!fnToSutsTCs[fn]) fnToSutsTCs[fn] = new Set();
        fnToSutsTCs[fn].add(row.testcase);
      }

      const details = [];
      const allReqs = new Set();
      const allStsTcs = new Set();

      for (const [fn, changeType] of activeFnEntries) {
        const reqs = funcToReqs[fn] ? [...funcToReqs[fn]] : [];
        reqs.forEach(r => allReqs.add(r));

        const stsTcSet = new Set();
        for (const rid of reqs) {
          (reqToStsTCs[rid] || new Set()).forEach(tc => { stsTcSet.add(tc); allStsTcs.add(tc); });
        }

        const sutsTcList = fnToSutsTCs[fn] ? [...fnToSutsTCs[fn]] : [];
        const hop = (activeImpactGroups.direct || []).includes(fn) ? 'direct'
          : (activeImpactGroups.indirect_1hop || []).includes(fn) ? '1-hop'
          : (activeImpactGroups.indirect_2hop || []).includes(fn) ? '2-hop' : 'direct';

        details.push({
          function: fn,
          changeType,
          asil: functionMeta[fn]?.asil || '',
          coverage: coverageByFn[fn] || null,
          hop,
          requirements: reqs,
          stsTestCases: [...stsTcSet],
          sutsTestCases: sutsTcList,
          udsAction: actions.uds,
          stsAction: actions.sts,
          sutsAction: actions.suts,
          sdsAction: actions.sds,
        });
      }

      setGuide({
        details,
        summary: {
          changedFiles: changedFiles.length,
          changedFunctions: changedFnEntries.length,
          impactedReqs: allReqs.size,
          impactedStsTCs: allStsTcs.size,
          directFns: (impactGroups.direct || []).length,
          hop1Fns: (impactGroups.indirect_1hop || []).length,
          hop2Fns: (impactGroups.indirect_2hop || []).length,
        },
      });

      // Fetch AI risk/cross-doc guide (best-effort)
      try {
        const aiData = await post('/api/impact/ai-guide', {
          changed_types: Object.fromEntries(activeFnEntries),
          impact_groups: activeImpactGroups,
          // 함수별 ASIL을 함께 보내 위험평가가 실제 ASIL을 반영(없으면 'ASIL 미상'으로 정직 표시).
          by_name: Object.fromEntries(
            Object.entries(functionMeta).map(([fn, m]) => [fn, { asil: m?.asil || '' }]),
          ),
        });
        if (aiData?.ok) setAiGuide(aiData.guide);
      } catch (_) { /* AI guide is optional */ }

      toast('success', '영향도 가이드 생성 완료');
    } catch (e) {
      toast('error', `가이드 생성 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [activeFnEntries, linkedDocs, actions, activeImpactGroups, activeChangedFiles, functionMeta, coverageByFn, toast]);


  // 영향받은 함수 집합(직접+간접+변경)을 추적성 매트릭스 focus로 넘기고 SRS/SDS 탭으로 이동.
  // 기존 추적성 UI(SrsSdsSection의 V-model 매트릭스 + 정/역방향 공백 분석)를 재사용해
  // "이 변경이 어떤 요구사항/시험/커버리지 공백에 닿는지"를 그 화면에서 본다.
  const openInTraceability = useCallback(() => {
    const fns = [...new Set([
      ...activeFnEntries.map(([fn]) => fn),
      ...(activeImpactGroups.direct || []),
      ...(activeImpactGroups.indirect_1hop || []),
      ...(activeImpactGroups.indirect_2hop || []),
    ].filter(Boolean))];
    if (!fns.length) {
      toast('info', '영향받은 함수가 없습니다.');
      return;
    }
    try {
      localStorage.setItem('devops_v2_trace_focus', JSON.stringify({
        functions: fns, label: `변경 영향 함수 ${fns.length}개`, ts: Date.now(),
      }));
    } catch (_) { /* ignore */ }
    window.__detailSection?.('srssds');
  }, [activeFnEntries, activeImpactGroups, toast]);

  // Auto-enable demo if real data has no rich mappings (only header changes)
  const hasRichData = activeFnEntries.length > 1 || (guide?.summary?.impactedReqs > 0);

  if (!impact && !demoMode) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <div className="empty-title">변경 영향도 분석 결과가 없습니다</div>
        <div className="empty-desc">대시보드에서 동기화 & 분석을 실행하세요.<br />SCM에 base_ref가 설정되어야 변경 파일을 감지합니다.</div>
        <button className="btn-primary btn-sm" style={{ marginTop: 8 }} onClick={() => setDemoMode(true)}>데모 시나리오로 보기</button>
      </div>
    );
  }

  return (
    <div>
      {/* 백엔드 경고 표면화 — 과소보고/cloudium degrade/revision 불일치/ASIL escalation 등.
          0 영향을 '영향 없음'으로 오인하지 않도록 안전 신호를 의사결정 화면에 노출. */}
      {impactWarnings.length > 0 && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-warning)' }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>⚠️ 분석 경고 ({impactWarnings.length})</div>
          {impactWarnings.map((w, i) => {
            const danger = /under-reported|empty|escalation|미상|과소|MC\/DC|unavailable/i.test(String(w));
            return (
              <div key={i} className="text-sm" style={{ color: danger ? 'var(--color-danger)' : 'var(--text-muted)', padding: '1px 0' }}>
                • {w}
              </div>
            );
          })}
        </div>
      )}
      {/* ASIL 차등 검증 — 직접 변경 함수의 최대 ASIL → 검증강도(escalation·MC/DC 필수·커버리지 타깃)
          를 결정론적으로 표면화(ai-guide 선택 호출과 독립, 항상 노출). 미상은 QM 단정 금지로 경고. */}
      {asilInfo && (asilInfo.max_changed || asilInfo.escalation || (asilInfo.unknown_changed_count || 0) > 0) && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: `3px solid ${asilInfo.escalation ? 'var(--color-danger)' : 'var(--border)'}` }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>🛡️ ASIL 차등 검증</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11 }}>
            <span>변경 최대 ASIL:&nbsp;
              {asilInfo.max_changed && /^[A-D]$/.test(asilInfo.max_changed)
                ? <span className={`pill ${/[CD]/.test(asilInfo.max_changed) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 9 }}>{asilInfo.max_changed}</span>
                : <span className="text-muted">미상</span>}
            </span>
            {asilInfo.escalation && <StatusBadge tone="danger">Escalation (ASIL B+ 직접변경 — AUTO→검토)</StatusBadge>}
            {asilInfo.mcdc_required && <span className="pill pill-danger" style={{ fontSize: 9 }}>MC/DC 필수</span>}
            {asilInfo.coverage_target && <span className="pill pill-info" style={{ fontSize: 9 }}>커버리지 타깃: {asilInfo.coverage_target}</span>}
            {(asilInfo.unknown_changed_count || 0) > 0 && (
              <span className="pill pill-warning" style={{ fontSize: 9 }} title="ASIL 미상 직접변경 — 안전 등급 수동 확인 필요(QM 단정 금지)">
                ASIL 미상 {asilInfo.unknown_changed_count}개
              </span>
            )}
          </div>
        </div>
      )}
      {/* MC/DC delta — VectorCAST 커버리지 ASIL 타깃 대비 gap + 이력 회귀 요약. */}
      {coverageGap?.available && (
        <div className="panel" style={{ marginBottom: 12,
          borderLeft: `3px solid ${(coverageGap.summary?.below_target || coverageGap.summary?.regressed) ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>
            🎯 커버리지 (ASIL 타깃 대비)
          </div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">평가된 영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{coverageGap.summary?.evaluated ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">목표 미달</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.below_target ? 'var(--color-danger)' : undefined }}>
                {coverageGap.summary?.below_target ?? 0}
              </div>
            </div>
            <div className="stat-card" title="매칭됐으나 해당 ASIL 타깃 메트릭(예: MC/DC) 데이터가 리포트에 없는 함수 — 증거 부재(시험 실패 아님)">
              <div className="text-muted text-sm">미측정</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.unmeasured ? 'var(--color-warning)' : undefined }}>
                {coverageGap.summary?.unmeasured ?? 0}
              </div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">직전 대비 회귀</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.regressed ? 'var(--color-danger)' : undefined }}>
                {coverageGap.summary?.regressed ?? 0}
              </div>
            </div>
          </div>
          {!coverageGap.summary?.had_baseline && (
            <div className="text-muted text-sm" style={{ marginTop: 4 }}>직전 스냅샷 없음 — 이번 실행을 기준으로 저장(다음 분석부터 Δ 표시).</div>
          )}
        </div>
      )}
      {/* 회귀시험 선정 — 영향 함수에 매핑된 기존 SUTS TC / SITS call-chain(재실행 대상 증거, ISO 26262). */}
      {regressionSet?.summary && ((regressionSet.summary.suts_tc_count || 0) > 0 || (regressionSet.summary.sits_chain_count || 0) > 0) && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-info)' }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>🔁 회귀시험 선정 (재실행 대상)</div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.impacted_function_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">SUTS 재실행 TC</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.suts_tc_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">SITS 영향 체인</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.sits_chain_count ?? 0}</div>
            </div>
          </div>
          {Object.keys(regressionSet.suts || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SUTS 재실행 TC (함수별)</div>
              <div style={{ maxHeight: 120, overflow: 'auto' }}>
                {Object.entries(regressionSet.suts).slice(0, 12).map(([fn, tcs]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(tcs || []).length} TC </span>
                    {(tcs || []).slice(0, 6).map((tc, i) => (
                      <span key={i} className="pill pill-neutral" style={{ fontSize: 8, margin: 1 }}>{tc}</span>
                    ))}
                    {(tcs || []).length > 6 && <span className="text-muted" style={{ fontSize: 8 }}> +{(tcs || []).length - 6}</span>}
                  </div>
                ))}
                {Object.keys(regressionSet.suts).length > 12 && (
                  <div className="text-muted" style={{ fontSize: 9 }}>+{Object.keys(regressionSet.suts).length - 12}개 함수 더</div>
                )}
              </div>
            </div>
          )}
          {Object.keys(regressionSet.sits || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SITS 영향 call-chain (함수별)</div>
              <div style={{ maxHeight: 100, overflow: 'auto' }}>
                {Object.entries(regressionSet.sits).slice(0, 10).map(([fn, chains]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(chains || []).length} 체인</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {/* Summary */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">변경 영향도 요약</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn-primary btn-sm" onClick={buildGuide} disabled={loading}>
              {loading ? '분석 중...' : '상세 가이드 생성'}
            </button>
            <button className="btn-sm" onClick={openInTraceability}
              title="영향받은 함수 집합으로 추적성 매트릭스(SRS↔SDS↔UDS↔STS↔SUTS↔SITS)를 필터해서 봅니다">
              추적성 매트릭스에서 보기
            </button>
            <button className="btn-sm" onClick={() => setDemoMode(!demoMode)}>
              {demoMode ? '실제 데이터' : '데모 시나리오'}
            </button>
          </div>
        </div>

        {demoMode && <div className="pill pill-warning" style={{ marginBottom: 8 }}>데모 모드 — 시뮬레이션 데이터</div>}

        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{activeChangedFiles.length}</div>
            <div className="stat-label">변경 파일</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{activeFnEntries.length}</div>
            <div className="stat-label">변경 함수</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(activeImpactGroups.direct || []).length}</div>
            <div className="stat-label">직접 영향</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(activeImpactGroups.indirect_1hop || []).length + (activeImpactGroups.indirect_2hop || []).length}</div>
            <div className="stat-label">간접 영향</div>
          </div>
          {guide && (
            <>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-warning)' }}>
                <div className="stat-value">{guide.summary.impactedReqs}</div>
                <div className="stat-label">영향 요구사항</div>
              </div>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-info)' }}>
                <div className="stat-value">{guide.summary.impactedStsTCs}</div>
                <div className="stat-label">검토 TC</div>
              </div>
            </>
          )}
        </div>

        {/* Document impact status */}
        {(() => {
          // Build doc stats from guide details or actions
          const docStats = {};
          if (guide) {
            for (const d of guide.details) {
              if (d.requirements.length > 0) { docStats.uds = (docStats.uds || 0) + 1; }
              if (d.stsTestCases.length > 0) { docStats.sts = (docStats.sts || 0) + 1; }
              if (d.sutsTestCases.length > 0) { docStats.suts = (docStats.suts || 0) + 1; }
            }
            // SDS/SITS always affected if any function changed
            if (guide.details.length > 0) {
              docStats.sds = guide.details.length;
              docStats.sits = guide.details.filter(d => d.stsTestCases.length > 0).length || 0;
            }
          }
          const docEntries = [
            { key: 'uds', label: 'UDS', count: docStats.uds || actions.uds?.function_count || 0, status: actions.uds?.status },
            { key: 'sts', label: 'STS', count: docStats.sts || actions.sts?.function_count || 0, status: actions.sts?.status, extra: guide ? `${guide.summary.impactedStsTCs} TC` : '' },
            { key: 'suts', label: 'SUTS', count: docStats.suts || actions.suts?.function_count || 0, status: actions.suts?.status },
            { key: 'sits', label: 'SITS', count: docStats.sits || actions.sits?.function_count || 0, status: actions.sits?.status },
            { key: 'sds', label: 'SDS', count: docStats.sds || actions.sds?.function_count || 0, status: actions.sds?.status },
          ];
          return (
            <div style={{ marginTop: 10 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>문서별 영향</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {docEntries.map(d => {
                  const hasImpact = d.count > 0;
                  const st = d.status ? (DOC_STATUS[d.status] || { tone: 'neutral', label: d.status })
                    : (hasImpact ? { tone: 'warning', label: '검토 필요' } : { tone: 'neutral', label: '영향 없음' });
                  return (
                    <div key={d.key} style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid ${hasImpact ? 'var(--color-warning)' : 'var(--border)'}`, background: 'var(--bg)', minWidth: 100 }}>
                      <div style={{ fontWeight: 700, fontSize: 12, textTransform: 'uppercase' }}>{d.label}</div>
                      <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
                      {d.count > 0 && <span className="text-muted" style={{ fontSize: 10, marginLeft: 4 }}>{d.count} 함수</span>}
                      {d.extra && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{d.extra}</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}
      </div>

      {/* AI Risk & Cross-Document Impact Guide */}
      {aiGuide && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="panel-header">
            <span className="panel-title">AI 영향도 분석 가이드</span>
            <span className="text-muted text-sm">{aiGuide.ai_enriched ? 'AI-enriched' : 'deterministic'}</span>
          </div>

          {/* Risk Assessment */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 10, alignItems: 'center' }}>
            <div style={{
              padding: '8px 16px', borderRadius: 6, fontWeight: 700, fontSize: 14,
              background: aiGuide.risk?.grade === 'CRITICAL' ? 'var(--color-danger)' :
                aiGuide.risk?.grade === 'HIGH' ? '#e67e22' :
                aiGuide.risk?.grade === 'MEDIUM' ? 'var(--color-warning)' :
                aiGuide.risk?.grade === 'LOW' ? 'var(--color-success)' : '#888',
              color: '#fff',
            }}>
              {aiGuide.risk?.grade} ({aiGuide.risk?.score}/100)
            </div>
            <div style={{ fontSize: 11 }}>
              <div>ASIL: <strong>{aiGuide.risk?.max_asil}</strong></div>
              {aiGuide.risk?.asil_escalation && (
                <StatusBadge tone="danger">ASIL Escalation</StatusBadge>
              )}
            </div>
            <div style={{ flex: 1, fontSize: 10, color: 'var(--text-muted)' }}>
              {aiGuide.risk?.justification}
            </div>
          </div>

          {/* Safety Functions */}
          {aiGuide.risk?.affected_safety_functions?.length > 0 && (
            <div style={{ marginBottom: 10, padding: 8, background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--color-danger)' }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>안전 관련 함수</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {aiGuide.risk.affected_safety_functions.map((sf, i) => (
                  <span key={i} className="pill pill-danger" style={{ fontSize: 9 }}>{sf}</span>
                ))}
              </div>
            </div>
          )}

          {/* Cross-Document Impact */}
          {aiGuide.cross_doc_impacts && Object.keys(aiGuide.cross_doc_impacts).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6 }}>문서별 변경 영향</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 6 }}>
                {Object.entries(aiGuide.cross_doc_impacts).map(([doc, impacts]) => {
                  const items = Array.isArray(impacts) ? impacts : [];
                  return (
                    <div key={doc} style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
                      <div style={{ fontWeight: 700, fontSize: 11, textTransform: 'uppercase', marginBottom: 4, color: 'var(--accent)' }}>{doc}</div>
                      {items.slice(0, 3).map((imp, i) => (
                        <div key={i} style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{imp}</div>
                      ))}
                      {items.length > 3 && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>+{items.length - 3}건 더</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Review Checklist */}
          {aiGuide.review_checklist?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>리뷰 체크리스트</div>
              {aiGuide.review_checklist.map((item, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0', fontSize: 11 }}>
                  <span className={`pill ${item.priority === 'CRITICAL' ? 'pill-danger' : item.priority === 'HIGH' ? 'pill-warning' : 'pill-info'}`}
                    style={{ fontSize: 9, minWidth: 60, textAlign: 'center' }}>{item.priority}</span>
                  <span>{item.item}</span>
                </div>
              ))}
            </div>
          )}

          {/* Test Recommendations */}
          {aiGuide.test_recommendations?.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>테스트 추가 제안</div>
              <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>함수</th>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>유형</th>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>설명</th>
                  </tr>
                </thead>
                <tbody>
                  {aiGuide.test_recommendations.slice(0, 8).map((rec, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-light, var(--border))' }}>
                      <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontWeight: 600 }}>{rec.function}</td>
                      <td style={{ padding: '3px 6px' }}><span className="pill pill-info" style={{ fontSize: 9 }}>{rec.test_type}</span></td>
                      <td style={{ padding: '3px 6px' }}>{rec.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Detailed guide */}
      {guide && (
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">함수별 변경 가이드 ({guide.details.length}개)</span>
          </div>

          {/* Search + Filter */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="text" placeholder="함수명, 요구사항 ID 검색..."
              value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
              style={{ flex: 1, minWidth: 180, padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }} />
            <select value={hopFilter} onChange={e => setHopFilter(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
              <option value="all">전체 영향</option>
              <option value="direct">직접 영향</option>
              <option value="1-hop">1-hop</option>
              <option value="2-hop">2-hop</option>
            </select>
            <select value={docFilter} onChange={e => setDocFilter(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
              <option value="all">전체 문서</option>
              <option value="has_reqs">요구사항 있음</option>
              <option value="has_sts">STS TC 있음</option>
              <option value="has_suts">SUTS TC 있음</option>
              <option value="no_mapping">매핑 없음</option>
            </select>
            <span className="text-muted text-sm">{filteredGuide.length}/{guide.details.length}건</span>
          </div>

          <table className="impact-table" style={{ fontSize: 11 }}>
            <thead>
              <tr>
                <th style={{ width: 150 }}>함수</th>
                <th style={{ width: 60 }}>변경</th>
                <th style={{ width: 50 }}>ASIL</th>
                <th style={{ width: 50 }}>영향</th>
                <th style={{ width: 96 }} title="ASIL 타깃 구조 커버리지(D=MC/DC, C/B=분기, A/QM=구문) 대비. Δ=직전 대비 변화">커버리지</th>
                <th>요구사항</th>
                <th>STS TC</th>
                <th>SUTS TC</th>
                <th style={{ width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {filteredGuide.map((d, i) => (
                <tr key={i} style={{ background: d.hop === 'direct' ? 'var(--bg)' : undefined }}>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600 }}>{d.function}</td>
                  <td><span className="pill pill-warning" style={{ fontSize: 9 }}>{CHANGE_TYPE_KO[d.changeType] || d.changeType}</span></td>
                  <td>
                    {d.asil && /^[A-D]$/.test(d.asil)
                      ? <span className={`pill ${/[CD]/.test(d.asil) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 9 }}>{d.asil}</span>
                      : <span className="text-muted" style={{ fontSize: 9 }} title="ASIL 미상 — 수동 확인 필요">미상</span>}
                  </td>
                  <td><span className={`pill ${d.hop === 'direct' ? 'pill-danger' : 'pill-info'}`} style={{ fontSize: 9 }}>{d.hop}</span></td>
                  <td style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{renderCoverageCell(d.coverage)}</td>
                  <td style={{ fontSize: 10 }}>
                    {d.requirements.length > 0
                      ? <span title={d.requirements.join(', ')} style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}
                          onClick={() => window.__detailSection?.('srssds')}>
                          {d.requirements.length}개 ({d.requirements.slice(0, 2).join(', ')}{d.requirements.length > 2 ? '...' : ''})
                        </span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 10 }}>
                    {d.stsTestCases.length > 0
                      ? <span className="pill pill-info" style={{ fontSize: 9 }}>{d.stsTestCases.length} TC</span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 10 }}>
                    {d.sutsTestCases.length > 0
                      ? <span className="pill pill-info" style={{ fontSize: 9 }}>{d.sutsTestCases.length} TC</span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td>
                    <button className="btn-sm" style={{ fontSize: 9, padding: '1px 4px' }}
                      onClick={() => setSelectedFn(selectedFn === d.function ? null : d.function)}>
                      {selectedFn === d.function ? '접기' : '상세'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Detail panel for selected function */}
          {selectedFn && (() => {
            const d = guide.details.find(x => x.function === selectedFn);
            if (!d) return null;
            const ct = (d.changeType || '').toUpperCase();
            return (
              <div style={{ marginTop: 12, padding: 14, border: '2px solid var(--accent)', borderRadius: 8, background: 'var(--bg)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 15, fontFamily: 'monospace' }}>{d.function}</span>
                    <span className="pill pill-warning" style={{ fontSize: 10, marginLeft: 8 }}>{CHANGE_TYPE_KO[d.changeType] || d.changeType}</span>
                    <span className={`pill ${d.hop === 'direct' ? 'pill-danger' : 'pill-info'}`} style={{ fontSize: 10, marginLeft: 4 }}>{d.hop}</span>
                  </div>
                  {d.requirements.length > 0 && <span className="text-sm text-muted">영향 요구사항 {d.requirements.length}개</span>}
                </div>

                {/* Change description */}
                <div style={{ padding: '8px 10px', background: 'var(--panel)', borderRadius: 6, marginBottom: 12, fontSize: 12, borderLeft: '3px solid var(--color-warning)' }}>
                  {ct === 'BODY' && '함수 본문(로직)이 변경되었습니다. 동작 변경으로 인해 관련 문서의 Description, Test Action, Expected Result를 모두 재검토해야 합니다.'}
                  {ct === 'SIGNATURE' && '함수 시그니처(파라미터/리턴타입)가 변경되었습니다. 호출하는 모든 함수와 Input/Output Parameters, Pre-condition을 업데이트해야 합니다.'}
                  {ct === 'HEADER' && '헤더 파일이 변경되었습니다. 매크로/타입 정의 변경으로 이 헤더를 include하는 모든 소스 파일의 함수에 영향이 있을 수 있습니다.'}
                  {ct === 'VARIABLE' && '글로벌 변수가 변경되었습니다. 이 변수를 읽고 쓰는 모든 함수의 동작을 확인해야 합니다.'}
                  {ct === 'NEW' && '신규 함수가 추가되었습니다. UDS에 Function Information 항목을 추가하고, 관련 TC를 작성해야 합니다.'}
                  {ct === 'DELETE' && '함수가 삭제되었습니다. UDS에서 해당 함수를 제거하고, 관련 TC를 비활성화해야 합니다.'}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {/* UDS */}
                  <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>📘 UDS 업데이트</div>
                    {d.requirements.length > 0 ? (
                      <>
                        <div className="text-sm" style={{ marginBottom: 6 }}>다음 항목을 확인하고 업데이트하세요:</div>
                        <ul style={{ fontSize: 11, margin: '0 0 6px 16px', padding: 0 }}>
                          {ct === 'BODY' && <><li>Description — 변경된 로직 반영</li><li>Called Function — 호출 함수 변경 여부</li><li>Used Globals — 사용 변수 변경 여부</li></>}
                          {ct === 'SIGNATURE' && <><li>Prototype — 새 시그니처 반영</li><li>Input/Output Parameters — 파라미터 변경</li><li>Calling Function — 호출부 영향 확인</li></>}
                          {ct === 'VARIABLE' && <><li>Used Globals (Global/Static) — 변수 정의 업데이트</li><li>Description — 변수 변경에 따른 동작 변경</li></>}
                        </ul>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                          관련 요구사항: {d.requirements.slice(0, 5).join(', ')}{d.requirements.length > 5 ? ` +${d.requirements.length - 5}개` : ''}
                        </div>
                      </>
                    ) : (
                      <div className="text-sm text-muted">직접 매핑 없음 — 간접 영향 확인 필요</div>
                    )}
                  </div>

                  {/* STS */}
                  <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>📗 STS 검토</div>
                    {d.stsTestCases.length > 0 ? (
                      <>
                        <div className="text-sm" style={{ marginBottom: 6 }}><strong>{d.stsTestCases.length}개 TC</strong> 검토 필요:</div>
                        <ul style={{ fontSize: 11, margin: '0 0 6px 16px', padding: 0 }}>
                          {ct === 'BODY' && <><li>Test Action (Sequence) — 변경된 로직에 맞게 수정</li><li>Expected Result — 기대 결과 재확인</li><li>Pre-condition — 전제조건 변경 여부</li></>}
                          {ct === 'SIGNATURE' && <><li>Pre-condition — 파라미터 변경 반영</li><li>Test Action — 호출 방식 변경</li><li>Expected Result — 리턴값 변경 확인</li></>}
                          {ct === 'VARIABLE' && <><li>Test Action — 변수 초기값/설정 변경</li><li>Expected Result — 변수 기반 결과 변경</li></>}
                        </ul>
                        <div style={{ fontSize: 10, maxHeight: 60, overflow: 'auto' }}>
                          {d.stsTestCases.slice(0, 10).map(tc => (
                            <span key={tc} className="pill pill-neutral" style={{ fontSize: 9, margin: 1 }}>{tc}</span>
                          ))}
                          {d.stsTestCases.length > 10 && <span className="text-muted" style={{ fontSize: 9 }}> +{d.stsTestCases.length - 10}개</span>}
                        </div>
                      </>
                    ) : (
                      <div className="text-sm text-muted">직접 매핑된 TC 없음 — 관련 요구사항의 TC를 수동 확인</div>
                    )}
                  </div>

                  {/* SUTS */}
                  <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>📙 SUTS 업데이트</div>
                    {d.sutsTestCases.length > 0 ? (
                      <>
                        <div className="text-sm" style={{ marginBottom: 4 }}><strong>{d.sutsTestCases.length}개</strong> 단위 테스트 시퀀스 수정:</div>
                        <ul style={{ fontSize: 11, margin: '0 0 0 16px', padding: 0 }}>
                          <li>Input Variables — 입력값 업데이트</li>
                          <li>Output Variables — 기대 출력값 재검증</li>
                          <li>Sequences — 테스트 시퀀스 순서 확인</li>
                        </ul>
                      </>
                    ) : (
                      <div className="text-sm text-muted">해당 단위 TC 없음{d.hop !== 'direct' ? ' (간접 영향)' : ''}</div>
                    )}
                  </div>

                  {/* SDS */}
                  <div style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                    <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>📋 SDS 확인</div>
                    <div className="text-sm" style={{ marginBottom: 4 }}>SW Component 설계 문서 확인:</div>
                    <ul style={{ fontSize: 11, margin: '0 0 0 16px', padding: 0 }}>
                      {ct === 'SIGNATURE' && <li>Component Interface — 인터페이스 변경 반영</li>}
                      <li>Component Description — 동작 설명 확인</li>
                      <li>State Transition — 상태 전이 영향 확인</li>
                      {d.hop !== 'direct' && <li>Component Interaction — 간접 호출 관계 확인</li>}
                    </ul>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
