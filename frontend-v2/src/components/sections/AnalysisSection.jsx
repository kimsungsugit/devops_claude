import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { post, api } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { resolveCacheRoot } from '../../api.js';
import { saModules } from '../../staticAnalysis.js';
import { useAdminMode } from '../../contexts/AdminContext.jsx';
import PathPickerDialog from '../PathPickerDialog.jsx';

// VectorCAST 커버리지 셀({covered,total,rate}) → 통계 카드. rate는 0..1.
// 카드 값은 정수%(가독), 상세 라인엔 소수 둘째자리·분자/분모·미커버(total-covered)를 함께 표기
// (정수 반올림만으론 미커버 규모가 드러나지 않음 — 정직 표시).
function covCard(label, cell) {
  if (!cell || !cell.total) return null;
  const covered = typeof cell.covered === 'number' ? cell.covered : 0;  // covered 부재 시 0 — NaN 방지
  const ratio = typeof cell.rate === 'number' ? cell.rate : covered / cell.total;
  const pct = Math.round(ratio * 100);
  const uncov = Math.max(0, cell.total - covered);  // 데이터 손상(covered>total)에도 음수 방지
  const color = pct >= 80 ? 'var(--color-success)' : 'var(--color-warning)';
  return (
    <div className="stat-card" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="stat-value" style={{ color }}>{pct}%</div>
      <div className="stat-label">{label}</div>
      <div className="text-muted" style={{ fontSize: 9 }}>{covered.toLocaleString()}/{cell.total.toLocaleString()} ({(ratio * 100).toFixed(2)}%)</div>
      <div className="text-muted" style={{ fontSize: 9 }}>미커버 {uncov.toLocaleString()}</div>
    </div>
  );
}

// 데이터 출처 배지 — 🔵 Jenkins 빌드 산출물 / 🟢 SCM 직접로드(cloudium). 같은 vcast_summary 형태지만
// 출처에 따라 가용 필드가 다름(Jenkins=함수콜 포함, SCM 폴백=구문/분기/MC/DC만)을 사용자에게 알린다.
function SourceBadge({ source }) {
  if (!source) return null;
  const jk = source === 'jenkins';
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 10, whiteSpace: 'nowrap',
      color: jk ? '#1d4ed8' : '#047857', background: jk ? '#dbeafe' : '#d1fae5' }}>
      {jk ? '🔵 Jenkins 빌드' : '🟢 SCM 직접로드'}
    </span>
  );
}

// 커버리지 셀({covered,total,rate}) → 백분율(0..100) 또는 null(데이터 없음). rate 우선, 없으면 covered/total.
function pctOf(cell) {
  if (!cell || !cell.total) return null;
  return Math.round((typeof cell.rate === 'number' ? cell.rate : cell.covered / cell.total) * 100);
}

// entries[] → Map(unit → [{...entry, _kind}]) — 모듈(unit)별 함수 커버리지 드릴다운용.
// UT/IT를 각각 넘겨 한 종류만 담는다(과거엔 UT+IT를 한 맵에 합쳐 유닛테스트 패널에 IT가 섞였다).
function buildModuleMap(entries, kind) {
  const m = new Map();
  for (const e of (Array.isArray(entries) ? entries : [])) {
    const unit = (e?.unit ?? '').trim();
    if (!unit) continue;
    if (!m.has(unit)) m.set(unit, []);
    m.get(unit).push({ ...e, _kind: kind });
  }
  return m;
}

// build 모듈 목록(kpis.vectorcast.ut/it.modules) 우선, 없으면 entries를 unit별 구문/분기 집계로
// 파생. 각 행에 함수 entries(드릴다운용)를 join하고 커버리지 낮은 순 정렬.
function deriveCoverageModules(buildModules, fnMap) {
  if (Array.isArray(buildModules) && buildModules.length > 0) {
    return [...buildModules]
      .map(m => ({ name: m.name, lineRate: m.line_rate, branchRate: m.branch_rate, functions: fnMap.get(m.name) || [] }))
      .sort((a, b) => (a.lineRate ?? 101) - (b.lineRate ?? 101));
  }
  const out = [];
  for (const [unit, fns] of fnMap.entries()) {
    let sc = 0, st = 0, bc = 0, bt = 0;
    for (const f of fns) {
      if (f.statements?.total) { sc += f.statements.covered; st += f.statements.total; }
      if (f.branches?.total) { bc += f.branches.covered; bt += f.branches.total; }
    }
    out.push({
      name: unit,
      lineRate: st ? Math.round((sc / st) * 1000) / 10 : null,
      branchRate: bt ? Math.round((bc / bt) * 1000) / 10 : null,
      functions: fns,
    });
  }
  return out.sort((a, b) => (a.lineRate ?? 101) - (b.lineRate ?? 101));
}

// 모듈 커버리지 행 — 클릭 시 그 모듈(unit) 소속 함수별 커버리지로 드릴다운. 함수 entries는 scmVcast 로드 시 채워짐.
// UT 함수는 구문/분기, IT 함수는 함수콜 셀을 가지므로 pctOf로 null이면 자동 생략(셀 종류가 출처/시험에 따라 다름).
function ModuleCovRow({ name, lineRate, branchRate, functions }) {
  const [open, setOpen] = useState(false);
  const has = Array.isArray(functions) && functions.length > 0;
  const clr = (v) => (v == null ? 'var(--text-muted)' : v < 80 ? 'var(--color-danger)' : v < 95 ? 'var(--color-warning)' : 'var(--color-success)');
  return (
    <>
      <tr style={{ background: lineRate != null && lineRate < 80 ? '#fee2e2' : lineRate != null && lineRate < 95 ? '#fef9c3' : undefined, cursor: has ? 'pointer' : 'default' }}
        onClick={() => has && setOpen(o => !o)}
        role={has ? 'button' : undefined} tabIndex={has ? 0 : undefined}
        onKeyDown={(e) => { if (has && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setOpen(o => !o); } }}>
        <td style={{ fontFamily: 'monospace', fontSize: 10 }}>
          {has && <span style={{ marginRight: 4, color: 'var(--text-muted)' }}>{open ? '▾' : '▸'}</span>}
          {name}
          {has && <span className="text-muted" style={{ fontSize: 9, marginLeft: 4 }} title="복수 VectorCAST 환경/폴더에서 수집된 함수 결과 행(엔트리) 수 — 고유 함수 수가 아닐 수 있음(폴더간 중복 미제거)">({functions.length} 함수 엔트리)</span>}
        </td>
        <td style={{ textAlign: 'center', fontWeight: 600, color: clr(lineRate) }}>{lineRate != null ? `${lineRate.toFixed(1)}%` : '-'}</td>
        <td style={{ textAlign: 'center', fontWeight: 600, color: clr(branchRate ?? 100) }}>{branchRate != null ? `${branchRate.toFixed(1)}%` : '-'}</td>
        <td style={{ width: 100 }}>
          <div style={{ height: 6, borderRadius: 3, background: '#e5e7eb', overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(lineRate ?? 0, 100)}%`, height: '100%', background: clr(lineRate) }} />
          </div>
        </td>
      </tr>
      {open && has && functions.map((f, j) => {
        const st = pctOf(f.statements), bn = pctOf(f.branches), mc = pctOf(f.pairs), fc = pctOf(f.function_calls);
        return (
          <tr key={`${f._kind}-${f.subprogram ?? f.function ?? j}`} style={{ background: 'var(--bg)' }}>
            <td style={{ paddingLeft: 20, fontFamily: 'monospace', fontSize: 9 }}>
              <span className="text-muted" style={{ marginRight: 4 }}>{f._kind}</span>{f.subprogram ?? f.function ?? '-'}
            </td>
            <td colSpan={3} style={{ fontSize: 9, padding: '2px 6px' }}>
              <span className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
                {st != null && <span>구문 <b style={{ color: clr(st) }}>{st}%</b></span>}
                {bn != null && <span>분기 <b style={{ color: clr(bn) }}>{bn}%</b></span>}
                {mc != null && <span>MC/DC <b style={{ color: clr(mc) }}>{mc}%</b></span>}
                {fc != null && <span>함수콜 <b style={{ color: clr(fc) }}>{fc}%</b></span>}
                <span className="text-muted">CC {f.ccn ?? '-'}</span>
              </span>
            </td>
          </tr>
        );
      })}
    </>
  );
}

// SwUTCV/SwITCV 정합성 검증(Coverage Report ↔ SUTR/SITR) 결과 카드. ConsistencyReport.to_dict 형태
// ({ ok, issues:[{severity,category,message}], coverage_summary, sutr_summary, parse_warnings })를 렌더.
// 커버리지 결과(coverage_summary)는 빌더 Coverage Report의 Traceability/Coverage 시트에서 파싱된 값이라
// '미커버 함수·Exception·Total TC·Final Result'를 그대로 보여준다. severity 색은 SwUTBuildSection과
// 동일한 전역 CSS(swut-issue-${severity})에 위임. peerLabel = 'SUTR'(UT) | 'SITR'(IT).
function ConsistencyResult({ report, peerLabel = 'SUTR', hideVerdict = false }) {
  if (!report) return null;
  const issues = report.issues || [];
  const pw = report.parse_warnings || [];
  const cs = report.coverage_summary || {};
  const ss = report.sutr_summary || {};
  const exc = (cs.exception_statement || 0) + (cs.exception_branch || 0);
  const uncovered = Array.isArray(cs.uncovered_functions) ? cs.uncovered_functions.length : null;
  const hasCov = cs.total_tcs != null || cs.total_functions != null || uncovered != null || cs.final_result;
  const hasPeer = ss.total_tcs != null || ss.passed != null || ss.failed != null;
  return (
    <div className="swut-consistency-result" style={{ marginTop: 8 }}>
      {/* hideVerdict: 단일 산출물 직접 파싱(정합성 비교 아님) — PASS/FAIL·issue 헤더 생략 */}
      {!hideVerdict && (
        <div className="swut-consistency-status">
          결과: <strong>{report.ok ? '✅ PASS' : '⚠️ FAIL'}</strong>{' '}
          — issue {issues.length}건, warning {pw.length}건
        </div>
      )}
      {hideVerdict && !hasCov && !hasPeer && pw.length === 0 && (
        <div className="text-sm text-muted">추출된 결과가 없습니다 — 시트명/헤더 구조를 확인하세요.</div>
      )}
      {hasCov && (
        <div className="stats-row" style={{ marginTop: 6 }}>
          {cs.total_tcs != null && (
            <div className="stat-card"><div className="stat-value">{cs.total_tcs.toLocaleString()}</div><div className="stat-label">Traceability TC</div></div>
          )}
          {cs.total_functions != null && (
            <div className="stat-card"><div className="stat-value">{cs.total_functions.toLocaleString()}</div><div className="stat-label">함수·항목</div></div>
          )}
          {uncovered != null && (
            <div className="stat-card" style={{ borderLeft: `3px solid ${uncovered > 0 ? 'var(--color-warning)' : 'var(--color-success)'}` }}>
              <div className="stat-value" style={{ color: uncovered > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{uncovered}</div>
              <div className="stat-label">미커버 함수</div>
            </div>
          )}
          {(cs.exception_statement != null || cs.exception_branch != null) && (
            <div className="stat-card"><div className="stat-value">{exc.toLocaleString()}</div><div className="stat-label">Exception</div></div>
          )}
          {cs.final_result && (
            <div className="stat-card"><div className="stat-value" style={{ fontSize: 12 }}>{cs.final_result}</div><div className="stat-label">Coverage 결과</div></div>
          )}
        </div>
      )}
      {hasPeer && (
        <div className="stats-row" style={{ marginTop: 6 }}>
          {ss.total_tcs != null && (
            <div className="stat-card"><div className="stat-value">{ss.total_tcs.toLocaleString()}</div><div className="stat-label">{peerLabel} TC</div></div>
          )}
          {ss.passed != null && (
            <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}><div className="stat-value" style={{ color: 'var(--color-success)' }}>{ss.passed.toLocaleString()}</div><div className="stat-label">통과</div></div>
          )}
          {ss.failed != null && (
            <div className="stat-card" style={{ borderLeft: `3px solid ${ss.failed > 0 ? 'var(--color-danger)' : 'var(--color-success)'}` }}><div className="stat-value" style={{ color: ss.failed > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{ss.failed.toLocaleString()}</div><div className="stat-label">실패</div></div>
          )}
          {ss.not_executed != null && (
            <div className="stat-card"><div className="stat-value">{ss.not_executed.toLocaleString()}</div><div className="stat-label">미실행</div></div>
          )}
          {ss.deviated != null && (
            <div className="stat-card"><div className="stat-value">{ss.deviated.toLocaleString()}</div><div className="stat-label">Deviation</div></div>
          )}
          {ss.final_result && (
            <div className="stat-card"><div className="stat-value" style={{ fontSize: 12 }}>{ss.final_result}</div><div className="stat-label">{peerLabel} 결과</div></div>
          )}
        </div>
      )}
      {issues.length > 0 && (
        <ul className="swut-issues-list">
          {issues.map((iss, i) => (
            <li key={i} className={`swut-issue swut-issue-${iss.severity || 'info'}`}>
              <span className="swut-issue-cat">[{iss.category}]</span>{' '}
              {iss.message}
            </li>
          ))}
        </ul>
      )}
      {pw.length > 0 && (
        <ul className="swut-warnings-list">
          {pw.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
    </div>
  );
}

// 정합성 검증용 파일 경로 입력 행 (경로 텍스트 + admin 전용 Browse). 빌더 섹션의 Field/Browse 패턴 축약.
function PathRow({ label, value, onChange, onBrowse, isAdmin, browseTitle, placeholder }) {
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
      <label style={{ fontSize: 11, fontWeight: 600, minWidth: 104 }}>{label}</label>
      <input
        type="text" value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck="false"
        data-form-type="other" data-lpignore="true"
        style={{ flex: 1, minWidth: 180, fontSize: 11, fontFamily: 'monospace', padding: '4px 6px',
          border: '1px solid var(--border)', borderRadius: 4 }}
      />
      <button
        type="button" className="btn-secondary"
        disabled={!isAdmin} title={isAdmin ? undefined : browseTitle}
        onClick={onBrowse} style={{ fontSize: 11, padding: '4px 8px' }}
      >📂 찾기</button>
    </div>
  );
}

// 복잡도 값 추출 — 빌드 complexity.csv는 ccn을 '문자열'로 반환(read_csv_rows)하므로 Number 강제.
// SCM complexity_rows는 complexity(int). 비유효값은 0. (문자열이면 typeof 필터/비교가 깨져 차트 누락)
function ccOf(r) {
  const v = Number(r?.complexity ?? r?.cc ?? r?.ccn);
  return Number.isFinite(v) ? v : 0;
}

// 복잡도 × 커버리지 산포도 — 各 점=함수, X=구문 커버리지%, Y=CC. 좌상단(高복잡·低커버) = ISO 26262
// MC/DC 보강 1순위 사분면(음영). 단일 변수 막대 분포가 못 보여주는 '복잡한데 안 짜인 테스트'를 한눈에.
// 외부 차트 라이브러리 없이 순수 SVG(프로젝트 규칙: 막대 분포도 div로 그림). props는 join 완료된 points.
function ComplexityScatter({ points, naCount, yMax, threshold }) {
  const [hover, setHover] = useState(null);   // 마우스 올린 포인트 { p, x, y } | null
  const W = 480, H = 200, ML = 36, MR = 12, MT = 12, MB = 26;
  const pw = W - ML - MR, ph = H - MT - MB;
  const ym = yMax || 1;
  const xOf = (cov) => ML + (Math.max(0, Math.min(100, cov)) / 100) * pw;
  const yOf = (cc) => MT + (1 - Math.min(Math.max(cc, 0), ym) / ym) * ph;
  const thY = yOf(threshold);
  const x80 = xOf(80);
  const counts = { danger: 0, warning: 0, success: 0 };
  for (const p of points) counts[p.tone] = (counts[p.tone] || 0) + 1;
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="복잡도-커버리지 산포도"
        style={{ maxHeight: 240, display: 'block', overflow: 'visible' }}>
        {/* 위험 사분면(高복잡·低커버) 음영 */}
        <rect x={ML} y={MT} width={Math.max(0, x80 - ML)} height={Math.max(0, thY - MT)}
          fill="var(--color-danger)" opacity="0.07" />
        {/* 임계선(가로) / 80% 선(세로) */}
        <line x1={ML} y1={thY} x2={W - MR} y2={thY} stroke="var(--color-danger)" strokeOpacity="0.5" strokeDasharray="3 3" />
        <line x1={x80} y1={MT} x2={x80} y2={H - MB} stroke="var(--color-warning)" strokeOpacity="0.6" strokeDasharray="3 3" />
        {/* 축 */}
        <line x1={ML} y1={H - MB} x2={W - MR} y2={H - MB} stroke="var(--border)" />
        <line x1={ML} y1={MT} x2={ML} y2={H - MB} stroke="var(--border)" />
        {[0, 25, 50, 75, 100].map(t => (
          <text key={`x${t}`} x={xOf(t)} y={H - MB + 12} fontSize="8" fill="var(--text-muted)" textAnchor="middle">{t}</text>
        ))}
        {[0, threshold, Math.round(ym)].map((t, i) => (
          <text key={`y${i}`} x={ML - 4} y={yOf(t) + 3} fontSize="8" fill="var(--text-muted)" textAnchor="end">{t}</text>
        ))}
        <text x={x80 + 3} y={MT + 9} fontSize="8" fill="var(--color-danger)" opacity="0.85">위험</text>
        {points.map((p, i) => {
          // 정수 격자 과겹침 완화용 결정적 지터(±, Math.random 미사용 → 안정 렌더)
          const jx = (((i * 73) % 5) - 2) * 0.6;
          const jy = (((i * 37) % 5) - 2) * 0.6;
          const isHover = hover?.p === p;
          return (
            <circle key={i} cx={xOf(p.cov) + jx} cy={yOf(p.cc) + jy} r={isHover ? 4.5 : 3}
              fill={`var(--color-${p.tone})`} fillOpacity={isHover ? 0.95 : 0.6}
              stroke={isHover ? 'var(--text, #111)' : 'none'} strokeWidth={isHover ? 0.8 : 0}
              style={{ cursor: 'pointer' }}
              onMouseEnter={(e) => setHover({ p, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)} />
          );
        })}
      </svg>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
        <span>X=커버리지(구문%) · Y=복잡도(CC)</span>
        <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>● 위험 {counts.danger}</span>
        <span style={{ color: 'var(--color-warning)', fontWeight: 600 }}>● 주의 {counts.warning}</span>
        <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>● 양호 {counts.success}</span>
        {naCount > 0 && <span>커버리지 미상 {naCount}(산포 제외)</span>}
      </div>
      {hover && (
        <div data-testid="scatter-tooltip" style={{ position: 'fixed', left: hover.x + 12, top: hover.y + 12,
          zIndex: 50, pointerEvents: 'none', maxWidth: 260, padding: '6px 8px', fontSize: 11,
          background: 'var(--panel, #fff)', border: '1px solid var(--border)', borderRadius: 6,
          boxShadow: '0 2px 8px rgba(0,0,0,0.18)' }}>
          <div style={{ fontWeight: 700, fontFamily: 'monospace', wordBreak: 'break-all' }}>{hover.p.fn}</div>
          <div className="text-muted" style={{ fontSize: 10, wordBreak: 'break-all', marginBottom: 2 }}>{hover.p.file}</div>
          <div>복잡도 <b style={{ color: `var(--color-${hover.p.tone})` }}>{hover.p.cc}</b> · 구문 {hover.p.cov}%
            {hover.p.br != null ? ` · 분기 ${hover.p.br}%` : ''}{hover.p.mc != null ? ` · MC/DC ${hover.p.mc}%` : ''}</div>
        </div>
      )}
    </div>
  );
}

// 진행 중·완료된 SCM VectorCAST 잡을 job_url 단위로 보존한다. 원격 cloudium 파싱은 수 분 걸리는데,
// 그 사이 탭 전환·새로고침·job 변경(remount)·브라우저 백그라운드 throttle로 in-memory 폴링 루프가
// 끊기면 결과가 UI에 영영 안 실리고 스피너만 고착됐다. job_id를 남겨두면 재진입/포커스 복귀 시
// 폴링을 재개(완료면 즉시 적재)해 자동 복구한다.
const VCAST_JOB_KEY = 'devops_v2_vcast_jobs';
function _readVcastJobs() {
  try { return JSON.parse(localStorage.getItem(VCAST_JOB_KEY) || '{}') || {}; }
  catch { return {}; }
}
function saveVcastJob(jobUrl, jobId, startedAt) {
  if (!jobUrl || !jobId) return;
  const m = _readVcastJobs();
  // 실제 시작시각을 보존해야 재진입(remount/새로고침) 후에도 12분 timeout이 '원래 시작' 기준으로
  // 측정된다. 0(falsy)으로 저장하면 pollJob에서 t0가 Date.now()로 리셋돼 timeout이 무력화될 수 있다.
  m[jobUrl] = { jobId, startedAt: startedAt || Date.now() };
  try { localStorage.setItem(VCAST_JOB_KEY, JSON.stringify(m)); } catch { /* quota — best-effort */ }
}
function loadVcastJob(jobUrl) {
  if (!jobUrl) return null;
  const e = _readVcastJobs()[jobUrl];
  return (e && e.jobId) ? e : null;
}
function clearVcastJob(jobUrl) {
  if (!jobUrl) return;
  const m = _readVcastJobs();
  if (m[jobUrl] !== undefined) {
    delete m[jobUrl];
    try { localStorage.setItem(VCAST_JOB_KEY, JSON.stringify(m)); } catch { /* best-effort */ }
  }
}

// ── SCM 정적분석 도구 모듈 카드 (도구별 APP/BOOT 모듈 반복) ──────────────────

function SaModuleLabel({ m, extra }) {
  return (
    <div className="row" style={{ gap: 6, alignItems: 'center', marginBottom: 4 }}>
      <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 10,
        background: 'var(--accent, #0052cc)', color: 'var(--text-inverse, #fff)' }}>
        {m.label || '모듈'}
      </span>
      {extra && <span className="text-muted" style={{ fontSize: 10 }}>{extra}</span>}
    </div>
  );
}

function SaCodeSonarModule({ m }) {
  const s = m.summary || {};
  return (
    <div style={{ borderLeft: '2px solid var(--border, #d1d5db)', paddingLeft: 8, marginBottom: 8 }}>
      <SaModuleLabel m={m} extra={`${s.analysis_name || ''}${s.analysis_id ? ' #' + s.analysis_id : ''}`} />
      <div className="stats-row" style={{ marginBottom: 6 }}>
        <div className="stat-card" style={{ borderLeft: `3px solid ${(s.active_warnings || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)'}` }}>
          <div className="stat-value" style={{ color: (s.active_warnings || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{s.active_warnings ?? '-'}</div>
          <div className="stat-label">Active Warnings</div>
        </div>
        <div className="stat-card"><div className="stat-value">{s.file_count ?? '-'}</div><div className="stat-label">분석 파일</div></div>
        <div className="stat-card"><div className="stat-value">{s.distinct_classes ?? (m.by_class?.length ?? '-')}</div><div className="stat-label">경고 분류</div></div>
      </div>
      {Array.isArray(m.by_class) && m.by_class.length > 0 && (
        <details open style={{ marginBottom: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>경고 분류별</summary>
          <div style={{ marginTop: 6 }}>
            {m.by_class.map((c, i) => {
              const max = m.by_class[0]?.count || 1;
              return (
                <div key={i} className="row" style={{ gap: 8, alignItems: 'center', marginBottom: 3 }}>
                  <span className="text-sm" style={{ minWidth: 170, fontSize: 11 }}>{c.warning_class}</span>
                  <div style={{ flex: 1, height: 12, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.round((c.count / max) * 100)}%`, height: '100%', background: 'var(--color-warning)' }} />
                  </div>
                  <span className="text-sm" style={{ fontWeight: 700, minWidth: 28, textAlign: 'right' }}>{c.count}</span>
                </div>
              );
            })}
          </div>
        </details>
      )}
      {Array.isArray(m.by_file) && m.by_file.length > 0 && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>파일별 경고 (상위 {m.by_file.length})</summary>
          <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 6 }}>
            <table className="impact-table" style={{ fontSize: 10 }}>
              <thead><tr><th>파일</th><th>경고</th><th>라인</th><th>언어</th></tr></thead>
              <tbody>
                {m.by_file.map((f, i) => (
                  <tr key={i} style={{ background: f.warnings >= 10 ? '#fee2e2' : f.warnings >= 5 ? '#fef9c3' : undefined }}>
                    <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.file}</td>
                    <td style={{ textAlign: 'center', fontWeight: 700 }}>{f.warnings}</td>
                    <td style={{ textAlign: 'center' }}>{f.lines?.toLocaleString?.() ?? f.lines}</td>
                    <td style={{ textAlign: 'center' }}>{f.language}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function SaQacModule({ m, threshold }) {
  const s = m.summary || {};
  return (
    <div style={{ borderLeft: '2px solid var(--border, #d1d5db)', paddingLeft: 8, marginBottom: 8 }}>
      <SaModuleLabel m={m} />
      <div className="stats-row" style={{ marginBottom: 6 }}>
        <div className="stat-card"><div className="stat-value">{s.function_count ?? '-'}</div><div className="stat-label">함수 수</div></div>
        <div className="stat-card" style={{ borderLeft: `3px solid ${(s.vg_max || 0) > threshold ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
          <div className="stat-value" style={{ color: (s.vg_max || 0) > threshold ? 'var(--color-danger)' : 'var(--color-success)' }}>{s.vg_max ?? '-'}</div>
          <div className="stat-label">v(G) Max</div>
        </div>
        <div className="stat-card"><div className="stat-value">{s.vg_p95 ?? '-'}</div><div className="stat-label">v(G) P95</div></div>
        <div className="stat-card"><div className="stat-value">{s.vg_mean ?? '-'}</div><div className="stat-label">v(G) 평균</div></div>
        <div className="stat-card"><div className="stat-value" style={{ color: (s.vg_over_10 || 0) > 0 ? 'var(--color-warning)' : undefined }}>{s.vg_over_10 ?? '-'}</div><div className="stat-label">v(G)&gt;10</div></div>
      </div>
      {Array.isArray(m.top_functions) && m.top_functions.length > 0 && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>복잡도 상위 함수 (top {m.top_functions.length})</summary>
          <div style={{ maxHeight: 180, overflowY: 'auto', marginTop: 6 }}>
            <table className="impact-table" style={{ fontSize: 10 }}>
              <thead><tr><th>함수</th><th>v(G)</th></tr></thead>
              <tbody>
                {m.top_functions.map((f, i) => (
                  <tr key={i} style={{ background: f.vg > threshold ? '#fee2e2' : f.vg > threshold * 0.7 ? '#fef9c3' : undefined }}>
                    <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.function}</td>
                    <td style={{ textAlign: 'center', fontWeight: 700 }}>{f.vg}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function SaCpdModule({ m }) {
  return (
    <div style={{ borderLeft: '2px solid var(--border, #d1d5db)', paddingLeft: 8, marginBottom: 8 }}>
      <SaModuleLabel m={m} />
      <div className="stats-row" style={{ marginBottom: 6 }}>
        <div className="stat-card" style={{ borderLeft: `3px solid ${(m.duplication_blocks || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)'}` }}>
          <div className="stat-value" style={{ color: (m.duplication_blocks || 0) > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{m.duplication_blocks ?? '-'}</div>
          <div className="stat-label">중복 블록</div>
        </div>
        <div className="stat-card"><div className="stat-value">{m.total_dup_lines?.toLocaleString?.() ?? m.total_dup_lines ?? '-'}</div><div className="stat-label">중복 라인</div></div>
        <div className="stat-card"><div className="stat-value">{m.files_involved ?? '-'}</div><div className="stat-label">관련 파일</div></div>
      </div>
      {Array.isArray(m.top_blocks) && m.top_blocks.length > 0 && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>중복 블록 (큰 순 {m.top_blocks.length})</summary>
          <div style={{ maxHeight: 180, overflowY: 'auto', marginTop: 6 }}>
            <table className="impact-table" style={{ fontSize: 10 }}>
              <thead><tr><th>중복 라인</th><th>토큰</th><th>파일</th></tr></thead>
              <tbody>
                {m.top_blocks.map((b, i) => (
                  <tr key={i} style={{ background: b.lines >= 25 ? '#fee2e2' : b.lines >= 10 ? '#fef9c3' : undefined }}>
                    <td style={{ textAlign: 'center', fontWeight: 700 }}>{b.lines}</td>
                    <td style={{ textAlign: 'center' }}>{b.tokens}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{(b.files || []).join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function SaCodeEyeModule({ m }) {
  const s = m.summary || {};
  return (
    <div style={{ borderLeft: '2px solid var(--border, #d1d5db)', paddingLeft: 8, marginBottom: 8 }}>
      <SaModuleLabel m={m} />
      <div className="stats-row">
        <div className="stat-card"><div className="stat-value">{s.files_checked ?? '-'}</div><div className="stat-label">검사 파일</div></div>
        <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}><div className="stat-value" style={{ color: 'var(--color-success)' }}>{s.files_success ?? '-'}</div><div className="stat-label">검사 성공</div></div>
        <div className="stat-card" style={{ borderLeft: `3px solid ${(s.files_fail || 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)'}` }}><div className="stat-value" style={{ color: (s.files_fail || 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{s.files_fail ?? '-'}</div><div className="stat-label">검사 실패</div></div>
      </div>
      {s.purpose && (
        <div className="text-muted" style={{ fontSize: 10, marginTop: 4 }}>검사목적: {s.purpose} · 시작 {s.started}</div>
      )}
    </div>
  );
}

export default function AnalysisSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = resolveCacheRoot(analysisResult, job, cfg);

  const [complexity, setComplexity] = useState(null);
  const [complexityLoading, setComplexityLoading] = useState(false);
  const [compSort, setCompSort] = useState('complexity');
  const [compFilter, setCompFilter] = useState('');
  // SCM 등록 VectorCAST 경로 지연 로드(빌드 산출물에 결과가 없을 때). 무거운 cloudium 폴더
  // 파싱(~100s)이라 analyze 임계경로에 넣지 않고 사용자 명시 클릭 시에만 /report/vectorcast-rag
  // (build→cloudium 폴백 내장)를 호출한다.
  const [scmVcast, setScmVcast] = useState(null);
  const [scmVcastLoading, setScmVcastLoading] = useState(false);
  // 정적분석 도구 4종(CodeSonar/CPD/QAC HIS/CodeEye) SCM PDF·XML 지연 로드 — VectorCAST와 별개.
  const [sa, setSa] = useState(null);
  const [saLoading, setSaLoading] = useState(false);
  // 언마운트 후 폴링 루프가 setState/네트워크를 계속 돌지 않도록 가드(W2). 잡 자체는 서버에서
  // 계속 실행되며 결과는 TTL 캐시되므로, 재진입 시 재클릭하면 빠르게 받는다.
  const mountedRef = useRef(true);
  // StrictMode(dev)는 effect를 setup→cleanup→setup으로 이중 호출한다. cleanup만 두면 cleanup이
  // mountedRef를 false로 만든 뒤 재-setup이 복원하지 않아, mountedRef가 마운트 직후부터 false로
  // 고정된다 → 폴링 while(mountedRef.current)가 영영 안 돌고(=impact-job 요청 0), finally의
  // setScmVcastLoading(false)도 스킵돼 스피너가 고착된다. setup에서 매번 true로 복원해야 한다.
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  // 동시 폴링 루프 방지 — start/resume/focus 복구가 겹쳐도 한 번에 하나만 돈다.
  const pollingRef = useRef(false);

  const loadComplexity = useCallback(async () => {
    setComplexityLoading(true);
    try {
      const data = await post('/api/jenkins/report/complexity', {
        job_url: job.url, cache_root: cacheRoot, build_selector: cfg.buildSelector,
      });
      setComplexity(data ?? { rows: [] });
      // 빈 결과를 placeholder로 silent 되돌리지 않고 명시 안내(데이터 미동기화 vs 미클릭 구분).
      const n = (data?.rows ?? data?.functions ?? []).length;
      if (n === 0) toast('info', '이 빌드에 complexity.csv가 없습니다 (복잡도 데이터 미동기화).');
    } catch (e) {
      toast('error', `복잡도 조회 실패: ${e.message}`);
    } finally {
      setComplexityLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  // 정적분석 4종 로드 — SCM 등록 경로(linked_docs.codesonar=정적분석 폴더)에서 CodeSonar/CPD/QAC/CodeEye
  // 최신 리포트를 파싱. VectorCAST와 달리 동기(파싱 빠름) — cloudium worker read + PDF/XML 파싱은 초 단위.
  const loadStaticAnalysis = useCallback(async () => {
    const paths = analysisResult?.matchedScm?.linked_docs?.codesonar || [];
    if (!paths.length) { toast('info', 'SCM에 등록된 정적분석 경로가 없습니다.'); return; }
    setSaLoading(true);
    try {
      const data = await post('/api/jenkins/report/static-analysis', { paths });
      if (data?.ok) {
        setSa(data);
        const tools = ['codesonar', 'cpd', 'qac', 'codeeye'].filter(t => data[t]?.ok);
        toast('success', `정적분석 ${tools.length}종 로드 (${tools.join('·')})`);
      } else {
        setSa(data || { ok: false });
        toast('warning', `정적분석: ${data?.detail || '결과를 찾지 못했습니다'}`);
      }
    } catch (e) {
      toast('error', `정적분석 로드 실패: ${e.message}`);
    } finally {
      setSaLoading(false);
    }
  }, [analysisResult, toast]);

  // ── SwUTCV/SwITCV 정합성 검증 (Coverage Report ↔ SUTR/SITR) ──
  // 빌더가 생성한 산출물 2개의 경로를 받아 기존 /consistency/check 엔드포인트로 교차검증.
  // 분석 화면은 project_id를 모르고 SCM에 빌드 산출물 경로도 없으므로 사용자가 파일 경로를 지정한다.
  const { isAdmin } = useAdminMode();
  const browseDisabledTitle = '관리자 전용 — Ctrl+Shift+A로 admin 모드 활성화';
  const [picker, setPicker] = useState(null);   // { pattern, title, current, onSelect }
  // useCallback 안정화 — PathRow onBrowse 인라인 화살표가 매 렌더 새 함수가 되지 않도록(reviewer W1).
  const openPicker = useCallback((pickerCfg) => setPicker(pickerCfg), []);
  const [utcvForm, setUtcvForm] = useState({ coverage_path: '', sutr_path: '' });
  const [utcvReport, setUtcvReport] = useState(null);
  const [utcvChecking, setUtcvChecking] = useState(false);
  const [itcvForm, setItcvForm] = useState({ coverage_path: '', sitr_path: '' });
  const [itcvReport, setItcvReport] = useState(null);
  const [itcvChecking, setItcvChecking] = useState(false);
  // 단일 산출물 직접 파싱(정합성 비교 없이) — {coverage,report} 각 문서 요약 결과 + busy kind
  const [utDoc, setUtDoc] = useState({ coverage: null, report: null });
  const [utDocBusy, setUtDocBusy] = useState('');
  const [itDoc, setItDoc] = useState({ coverage: null, report: null });
  const [itDocBusy, setItDocBusy] = useState('');

  const runUtcvCheck = useCallback(async () => {
    if (!utcvForm.coverage_path || !utcvForm.sutr_path) {
      toast('warning', 'Coverage(.xlsx)와 SUTR(.xlsm) 파일 경로가 모두 필요합니다.'); return;
    }
    setUtcvChecking(true); setUtcvReport(null);
    try {
      const report = await post('/api/swut/consistency/check', utcvForm);
      if (!mountedRef.current) return;
      setUtcvReport(report);
      const n = (report?.issues || []).length;
      toast(n === 0 ? 'success' : 'warning',
        n === 0 ? 'SwUTCV 정합성 검증 통과 — issue 0건' : `SwUTCV 정합성: issue ${n}건 — 카드 확인`);
    } catch (e) {
      if (mountedRef.current) toast('error', `정합성 검증 실패: ${e.message}`);
    } finally {
      if (mountedRef.current) setUtcvChecking(false);
    }
  }, [utcvForm, toast]);

  const runItcvCheck = useCallback(async () => {
    if (!itcvForm.coverage_path || !itcvForm.sitr_path) {
      toast('warning', 'Coverage(.xlsx)와 SITR(.xlsm) 파일 경로가 모두 필요합니다.'); return;
    }
    setItcvChecking(true); setItcvReport(null);
    try {
      const report = await post('/api/swit/consistency/check', itcvForm);
      if (!mountedRef.current) return;
      setItcvReport(report);
      const n = (report?.issues || []).length;
      toast(n === 0 ? 'success' : 'warning',
        n === 0 ? 'SwITCV 정합성 검증 통과 — issue 0건' : `SwITCV 정합성: issue ${n}건 — 카드 확인`);
    } catch (e) {
      if (mountedRef.current) toast('error', `정합성 검증 실패: ${e.message}`);
    } finally {
      if (mountedRef.current) setItcvChecking(false);
    }
  }, [itcvForm, toast]);

  // 단일 산출물 직접 파싱 — 정합성 비교(두 문서 쌍) 없이 한 문서(kind: coverage|report)만
  // 파싱해 그 결과 요약을 표시. series='swut'|'swit', kind='coverage'|'report'.
  const parseDoc = useCallback(async (series, kind, path) => {
    if (!path) { toast('warning', '먼저 산출물 파일 경로를 입력하세요.'); return; }
    const setDoc = series === 'swut' ? setUtDoc : setItDoc;
    const setBusy = series === 'swut' ? setUtDocBusy : setItDocBusy;
    setBusy(kind);
    try {
      const res = await post(`/api/${series}/doc/summary`, { path, kind });
      if (!mountedRef.current) return;
      // _path 기록 → 경로가 바뀌면(타이핑/브라우즈) 카드 렌더 가드가 stale 카드를 자동 숨김.
      setDoc(d => ({ ...d, [kind]: { ...res, _path: path } }));
      const pw = (res?.parse_warnings || []).length;
      toast(pw ? 'warning' : 'success',
        pw ? `산출물 파싱 완료 — 경고 ${pw}건(카드 확인)` : '산출물 결과 파싱 완료');
    } catch (e) {
      // 실패 시 직전 성공 카드를 제거 — 토스트 사라진 뒤 옛 결과가 성공처럼 잔존하는 것 방지.
      if (mountedRef.current) {
        setDoc(d => ({ ...d, [kind]: null }));
        toast('error', `산출물 파싱 실패: ${e.message}`);
      }
    } finally {
      if (mountedRef.current) setBusy('');
    }
  }, [toast]);

  // 잡 상태를 폴링해 완료 시 결과를 적재한다. 최초 시작과 재진입/포커스 복구가 공용으로 호출한다.
  // poll-first 구조라 '이미 완료된 잡'으로 재진입하면 첫 폴에서 즉시 적재된다(3초 대기 없음).
  // jobUrl은 호출 시점의 job.url을 명시 전달받는다 — 클로저의 job?.url에 의존하면, keep-alive로
  // 같은 인스턴스에서 job prop만 바뀌는(향후 key 구조 변경) 경우 구 job의 보존 잡을 지울 수 있다(X1).
  const pollJob = useCallback(async (jobId, startedAtMs, jobUrl) => {
    if (!jobId || pollingRef.current) return;   // 중복 루프 차단
    pollingRef.current = true;
    if (mountedRef.current) setScmVcastLoading(true);
    const t0 = startedAtMs || Date.now();
    const TIMEOUT_MS = 12 * 60 * 1000;   // 12분 상한(최악 다폴더 파싱 + 여유). 보존된 시작시각 기준.
    try {
      while (mountedRef.current) {
        let st;
        try {
          st = await api(`/api/scm/impact-job/${jobId}`);
        } catch (e) {
          // 404(서버 재시작/프룬으로 잡 유실)·네트워크 오류 → 보존 잡 제거 후 종료(되살아나는 무한 폴링 방지).
          clearVcastJob(jobUrl);
          if (mountedRef.current && !/not found|404/i.test(String(e?.message || ''))) {
            toast('error', `VectorCAST 상태 조회 실패: ${e.message}`);
          }
          return;
        }
        const status = st?.job?.status;
        if (status === 'completed') {
          const data = st.job.result;
          clearVcastJob(jobUrl);
          if (!mountedRef.current) return;
          if (data?.ok && data.data) {
            setScmVcast(data);
            toast('success', `VectorCAST ${data.data.test_rows_count ?? 0}건 로드 (출처: ${data.source || 'cloudium'})`);
          } else {
            toast('warning', 'SCM 등록 경로에서 VectorCAST 결과를 찾지 못했습니다 (경로/레이아웃 확인).');
          }
          return;
        }
        if (status === 'failed') {
          clearVcastJob(jobUrl);
          if (mountedRef.current) toast('error', `VectorCAST 로드 실패: ${st.job?.error?.title || st.job?.error?.detail || 'unknown'}`);
          return;
        }
        if (Date.now() - t0 > TIMEOUT_MS) {
          clearVcastJob(jobUrl);
          if (mountedRef.current) toast('warning', 'VectorCAST 로딩 시간 초과 — 다시 시도하세요(캐시되어 빨라집니다).');
          return;
        }
        await new Promise(r => setTimeout(r, 3000));
        // queued/running → 계속 폴링
      }
    } finally {
      pollingRef.current = false;
      if (mountedRef.current) setScmVcastLoading(false);
    }
  }, [toast]);

  const loadScmVcast = useCallback(async () => {
    const paths = analysisResult?.matchedScm?.linked_docs?.vectorcast || [];
    // 빌드 산출물에 vcast가 있으면(HDPDM01) SCM 경로 없이도 async 엔드포인트가 빌드 캐시(vectorcast_rag.json)를
    // 읽어 함수레벨 entries를 반환한다(TDZ 회피 위해 analysisResult에서 직접 재계산).
    const bv = analysisResult?.reportData?.tester?.vectorcast || {};
    const hasBuild = (bv.test_rows_count || 0) > 0 || (bv.ut_reports || []).length > 0 || (bv.it_reports || []).length > 0;
    if (!paths.length && !hasBuild) { toast('info', 'SCM에 등록된 VectorCAST 경로가 없습니다.'); return; }
    if (pollingRef.current) return;   // 이미 진행 중 — 중복 잡 생성 방지
    setScmVcastLoading(true);   // 즉시 버튼 비활성/스피너 (POST 왕복 동안 더블클릭 차단)
    let jobId;
    try {
      // 원격 cloudium 폴더 파싱은 수 분 걸려 동기 호출 시 4~5분 블로킹(타임아웃/언마운트 abort로
      // '에러'처럼 보임) → 백그라운드 잡으로 던지고 폴링한다. 백엔드 TTL 캐시(30분)로 2회차+ 즉시.
      const start = await post('/api/jenkins/report/vectorcast-rag-async', {
        job_url: job.url, cache_root: cacheRoot, build_selector: cfg.buildSelector,
        vcast_log_paths: paths,
      });
      jobId = start?.job_id;
      if (!jobId) throw new Error('잡 생성에 실패했습니다.');
    } catch (e) {
      if (mountedRef.current) { toast('error', `VectorCAST 로드 실패: ${e.message}`); setScmVcastLoading(false); }
      return;
    }
    const startedAt = Date.now();
    saveVcastJob(job?.url, jobId, startedAt);   // 새로고침/탭이동/remount에도 재진입 자동복구되도록 보존
    toast('info', 'VectorCAST 원격 로그 파싱을 시작했습니다 (수 분 소요될 수 있습니다).');
    await pollJob(jobId, startedAt, job?.url);
  }, [analysisResult, job, cfg, cacheRoot, toast, pollJob]);

  // 재진입 자동복구(mount·job 변경 remount·새로고침) — 보존된 진행 중/완료 잡이 있으면 폴링 재개.
  // 완료된 잡이면 poll-first로 즉시 결과가 채워져, 사용자가 재클릭하지 않아도 데이터가 뜬다.
  useEffect(() => {
    if (!job?.url || scmVcast || pollingRef.current) return;
    const saved = loadVcastJob(job.url);
    if (saved?.jobId) pollJob(saved.jobId, saved.startedAt, job.url);
  }, [job, scmVcast, pollJob]);

  // 포커스 복구 — keep-alive(언마운트 안 함)에서 브라우저 백그라운드 throttle로 setTimeout 폴링이
  // 멎은 채 탭으로 돌아온 경우, 진행 중 잡을 재확인한다(중복 루프는 pollingRef로 차단).
  useEffect(() => {
    const recover = () => {
      if (document.hidden || scmVcast || pollingRef.current || !job?.url) return;
      const saved = loadVcastJob(job.url);
      if (saved?.jobId) pollJob(saved.jobId, saved.startedAt, job.url);
    };
    window.addEventListener('focus', recover);
    document.addEventListener('visibilitychange', recover);
    return () => {
      window.removeEventListener('focus', recover);
      document.removeEventListener('visibilitychange', recover);
    };
  }, [job, scmVcast, pollJob]);

  const rd = analysisResult?.reportData;
  const kpis = rd?.kpis || {};
  const prqa = kpis.prqa || {};
  const hmr = prqa.hmr_stats || {};
  const cm = kpis.code_metrics || {};
  const vc = kpis.vectorcast || {};
  const tester = rd?.tester || {};
  // VectorCAST 표시용 — SCM 지연로드 결과가 있으면 그걸, 없으면 빌드 산출물(tester.vectorcast).
  const scmVcastPaths = analysisResult?.matchedScm?.linked_docs?.vectorcast || [];
  const codesonarPaths = analysisResult?.matchedScm?.linked_docs?.codesonar || [];
  const buildVcast = tester?.vectorcast || {};
  const buildHasVcast = (buildVcast.test_rows_count || 0) > 0
    || (buildVcast.ut_reports || []).length > 0 || (buildVcast.it_reports || []).length > 0;
  const effVcast = scmVcast?.data
    ? {
        test_rows_count: scmVcast.data.test_rows_count,
        test_rows_count_ut: scmVcast.data.test_rows_count_ut ?? null,   // UT/IT 분리 TC 수 (P2)
        test_rows_count_it: scmVcast.data.test_rows_count_it ?? null,
        ut_reports: scmVcast.data.ut_reports || [],
        it_reports: scmVcast.data.it_reports || [],
        summary: scmVcast.data.summary || null,      // 통과/실패/pass_rate (P2, 결합)
        summary_ut: scmVcast.data.summary_ut || null,   // UT 전용 합부(backend _split_vcast_summary_by_source)
        summary_it: scmVcast.data.summary_it || null,   // IT 전용 합부 — 없으면 IT pass/fail 블록이 안 뜬다
        failures: scmVcast.data.failures || [],       // 실패 testcase 목록 (P2)
        _source: scmVcast.source || 'cloudium',
      }
    : buildVcast;
  // UT/IT 합부 분리 — 백엔드가 source(UT/IT)별로 나눈 summary. 분리값이 없으면(구 응답/빌드
  // 산출물) 결합 summary로 하위호환. UT 패널은 UT만, IT 패널은 IT만 표시.
  const sumUt = effVcast.summary_ut || null;
  const sumIt = effVcast.summary_it || null;
  const utSummary = sumUt || effVcast.summary || null;
  // 분리 summary(summary_ut)가 있으면 순수 UT, 없으면 결합값 fallback → 라벨을 정직하게.
  // (빌드 산출물/재시작 전 캐시는 분리 필드가 없어 결합값을 'UT'로 오표기하면 안 됨.)
  const utLabelSuffix = sumUt ? 'UT' : 'UT+IT';
  const utTcCount = effVcast.test_rows_count_ut ?? effVcast.test_rows_count ?? null;
  const itTcCount = effVcast.test_rows_count_it ?? null;
  // 실패 목록도 source(UT/IT)별 분리 — 백엔드 failures는 top-N 결합 목록이라 여기서 나눈다.
  const _allFailures = effVcast.failures || [];
  const utFailures = _allFailures.filter(f => String(f.source || '').toUpperCase() !== 'IT');
  const itFailures = _allFailures.filter(f => String(f.source || '').toUpperCase() === 'IT');
  const utCov = vc.ut || {};
  // SCM 경로 VectorCAST 커버리지(구문/분기/MC/DC) — UT/IT를 각 패널에 분리 귀속(합산 표시 안 함).
  // 단일 폴더는 coverage 하나가 그 폴더의 한 종류라 vcast_kind로 UT/IT를 안다. 다중 폴더 병합은
  // coverage_ut/coverage_it가 이미 분리돼 있다(backend jenkins.py _merge_vectorcast_payloads).
  const _scmData = scmVcast?.data || null;
  const _scmKind = String(_scmData?.vcast_kind || '').toUpperCase();
  const scmCovUt = _scmData?.coverage_ut || (_scmKind === 'UT' ? _scmData?.coverage : null) || null;
  const scmCovIt = _scmData?.coverage_it || (_scmKind === 'IT' ? _scmData?.coverage : null) || null;
  const qualityCfg = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_quality') || '{}'); } catch (_) { return {}; }
  })();
  // threshold 정규화 — localStorage 오염(빈문자/0/음수/문자열)이 버킷 라벨/비교를 깨지 않도록 1~200 클램프.
  let threshold = Number(qualityCfg.complexity);
  if (!Number.isFinite(threshold) || threshold < 1) threshold = 15;
  threshold = Math.min(threshold, 200);

  // 빌드 전체 Line/Branch 커버리지 카드는 제거됨 — 개요(ResultPanel) 'Line/Branch Cov'와 중복이고
  // 이 프로젝트는 빌드 라인커버가 0%라 무의미했다. UT/IT 커버리지는 각 패널의 scmCovUt/scmCovIt·
  // utCov/itCov로만 표시한다.

  // Complexity table — 빌드 complexity.csv가 없으면 SCM VectorCAST 폴더에서 추출한
  // 함수별 복잡도(complexity_rows)로 폴백(async VectorCAST 로드 시 자동 표시).
  // 빌드 complexity 응답이 비어도({rows:[]}) SCM 폴백이 nullish 단락으로 가려지지 않도록 길이 기반 폴백.
  // ⚠ useMemo 로 감싸야 한다 — `?? []` 폴백이 **매 렌더 새 배열**을 만들어, 이걸 deps 로 쓰는
  //   아래 세 useMemo(필터/정렬/집계)가 렌더마다 전부 재계산됐다(react-hooks/exhaustive-deps).
  const rows = useMemo(() => {
    const buildComplexityRows = complexity?.rows ?? complexity?.functions ?? [];
    return buildComplexityRows.length ? buildComplexityRows : (scmVcast?.data?.complexity_rows ?? []);
  }, [complexity, scmVcast]);
  const filteredRows = useMemo(() => {
    let items = [...rows];
    if (compFilter.trim()) {
      const q = compFilter.trim().toLowerCase();
      items = items.filter(r => (r.function ?? r.name ?? '').toLowerCase().includes(q) || (r.file ?? r.path ?? '').toLowerCase().includes(q));
    }
    items.sort((a, b) => {
      if (compSort === 'complexity') return ccOf(b) - ccOf(a);
      if (compSort === 'name') return (a.function ?? a.name ?? '').localeCompare(b.function ?? b.name ?? '');
      return 0;
    });
    return items;
  }, [rows, compFilter, compSort]);

  // 복잡도 분포 히스토그램(표 위 차트) — 임계값(threshold) 정렬 4구간, 색상은 표 행과 동일 위험도.
  // ISO 26262 HIS VG 관리 관점에서 임계 초과 함수 비중을 한눈에. 외부 차트 라이브러리 없이 순수 div.
  const compDist = useMemo(() => {
    const ccs = rows.map(ccOf).filter(v => v > 0);   // ccOf가 Number 강제(문자열 ccn도 정상 집계)
    if (!ccs.length) return null;
    const t = threshold;   // 이미 1~200로 정규화됨
    const wEnd = Math.max(1, Math.floor(t * 0.7));   // success 상한(표 행 `cc > t*0.7` 경계와 일치)
    const edges = [
      { label: `1–${wEnd}`, lo: 1, hi: wEnd, tone: 'success' },
      { label: `${wEnd + 1}–${t}`, lo: wEnd + 1, hi: t, tone: 'warning' },
      { label: `${t + 1}–${t * 2}`, lo: t + 1, hi: t * 2, tone: 'danger' },
      { label: `${t * 2 + 1}+`, lo: t * 2 + 1, hi: Infinity, tone: 'danger' },
    ].filter(e => e.lo <= e.hi);   // threshold 경계에서 역전(lo>hi) 버킷 제거
    const buckets = edges.map(e => ({ ...e, count: ccs.filter(v => v >= e.lo && v <= e.hi).length }));
    const maxCount = Math.max(1, ...buckets.map(b => b.count));
    const total = ccs.length;
    return {
      buckets, maxCount, total,
      max: Math.max(...ccs),
      avg: ccs.reduce((a, b) => a + b, 0) / total,
      over: ccs.filter(v => v > t).length,
    };
  }, [rows, threshold]);

  // 산포도 데이터(복잡도 × 커버리지) — complexity_rows(CC)에 함수별 커버리지(vcast_summary.entries)를
  // (unit, function/subprogram) 키로 join. 빌드 complexity.csv 경로엔 entries가 없어 join 0건 → 산포 미가용.
  // X=구문 커버리지%, Y=CC. 색: 高복잡&低커버=danger, 둘 중 하나=warning, 양호=success(임계/80% 경계).
  const compScatter = useMemo(() => {
    const vs = scmVcast?.data?.vcast_summary;
    if (!vs || typeof vs !== 'object') return { points: [], naCount: 0, yMax: 0 };
    // ut/it entries 합치기 → (unit,subprogram) & subprogram-only 두 맵. 중복 키는 statements.total 큰(증거 많은) 쪽.
    const byKey = new Map();   // `${unit} ${fn}` → entry
    const byFn = new Map();    // fn → entry(폴백: unit 표기 불일치 대비)
    const better = (e, prev) => !prev || (e?.statements?.total || 0) > (prev?.statements?.total || 0);
    for (const mk of ['ut_metrics', 'it_metrics']) {
      const arr = vs?.[mk]?.entries;
      if (!Array.isArray(arr)) continue;
      for (const e of arr) {
        const fn = (e?.subprogram ?? '').trim();
        if (!fn) continue;
        const unit = (e?.unit ?? '').trim();
        const k = `${unit} ${fn}`;
        if (better(e, byKey.get(k))) byKey.set(k, e);
        if (better(e, byFn.get(fn))) byFn.set(fn, e);
      }
    }
    const cellPct = (c) => (c && c.total
      ? Math.round((typeof c.rate === 'number' ? c.rate : c.covered / c.total) * 100) : null);
    const points = [];
    let naCount = 0;
    for (const r of rows) {
      const cc = ccOf(r);
      if (cc <= 0) continue;
      const unit = (r.unit ?? r.file ?? '').trim();
      const fn = (r.function ?? r.name ?? '').trim();
      const e = byKey.get(`${unit} ${fn}`) || byFn.get(fn);
      const stPct = cellPct(e?.statements);
      if (stPct == null) { naCount++; continue; }   // 커버리지 미상은 X=0 위장 대신 산포 제외
      const ccBad = cc > threshold;
      const covBad = stPct < 80;
      const tone = ccBad && covBad ? 'danger' : (ccBad || covBad ? 'warning' : 'success');
      points.push({
        fn, file: r.file ?? r.unit ?? '-', cc, cov: stPct,
        br: cellPct(e?.branches), mc: cellPct(e?.pairs), tone,
      });
    }
    // Math.max(...spread)는 수만 함수 규모에서 스택 한계 → reduce로 선형 누적(W2).
    const yMax = points.reduce((m, p) => (p.cc > m ? p.cc : m), points.length ? threshold * 2 : 0);
    return { points, naCount, yMax };
  }, [rows, scmVcast, threshold]);

  const scatterAvailable = compScatter.points.length > 0;

  // ── 함수레벨 데이터(UT/IT entries, function_calls, grand_totals) ──
  // 빌드완료(HDPDM01)든 SCM(KJPDS02)든 동일한 scmVcast.data.vcast_summary 형태로 흐른다.
  // reportData.tester.vectorcast엔 entries가 없으므로(reports/summary만), 함수레벨은 async 로드(scmVcast)로만 온다.
  // 빌드 캐시(vectorcast_rag.json)도 같은 엔드포인트가 즉시 반환 → Jenkins 라이브 연결 불필요.
  const vSum = scmVcast?.data?.vcast_summary || {};
  const utEntries = Array.isArray(vSum.ut_metrics?.entries) ? vSum.ut_metrics.entries : [];
  const itEntries = Array.isArray(vSum.it_metrics?.entries) ? vSum.it_metrics.entries : [];
  // utGrand 는 UT 카드가 함수레벨 entries 를 직접 쓰도록 바뀌며 쓰이지 않게 됐다(미사용 제거).
  const itGrand = vSum.it_metrics?.grand_totals || {};
  const fnLevelLoaded = utEntries.length > 0 || itEntries.length > 0;
  // 출처: SCM 로드면 그 source, 아니면 빌드에 vcast 있을 때 jenkins.
  const vcastSource = scmVcast?.source || (buildHasVcast ? 'jenkins' : null);
  // 함수레벨 상세 로드 가능 — 빌드에 vcast 있거나(캐시) SCM 경로 등록됨. 둘 중 하나면 async 로드 호출 가능.
  const canLoadFnLevel = buildHasVcast || scmVcastPaths.length > 0;

  // 모듈(unit)별 함수 entries — UT/IT를 분리해 각 패널이 자기 종류만 표시(모듈 드릴다운용).
  const moduleFnMapUt = useMemo(
    () => buildModuleMap(scmVcast?.data?.vcast_summary?.ut_metrics?.entries, 'UT'), [scmVcast]);
  const moduleFnMapIt = useMemo(
    () => buildModuleMap(scmVcast?.data?.vcast_summary?.it_metrics?.entries, 'IT'), [scmVcast]);

  // 커버리지 모듈 행 — 빌드 산출물 모듈(kpis.vectorcast.ut/it.modules) 우선, 없으면(SCM-only) entries를
  // unit별 집계로 파생. UT/IT 각각 산출해 해당 패널에만 표시(과거 UT+IT 합산 표는 제거).
  const coverageModulesUt = useMemo(
    () => deriveCoverageModules(analysisResult?.reportData?.kpis?.vectorcast?.ut?.modules, moduleFnMapUt),
    [analysisResult, moduleFnMapUt]);
  const coverageModulesIt = useMemo(
    () => deriveCoverageModules(analysisResult?.reportData?.kpis?.vectorcast?.it?.modules, moduleFnMapIt),
    [analysisResult, moduleFnMapIt]);

  return (
    <div>
      {/* ── 함수레벨 상세 로드 (전역) — UT/IT 함수별 커버리지·함수콜·드릴다운·산포도를 한 번에 채움 ── */}
      {!fnLevelLoaded && canLoadFnLevel && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-primary, #2563eb)' }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div className="text-sm" style={{ lineHeight: 1.5, flex: 1, minWidth: 240 }}>
              <b>함수레벨 상세</b>를 불러오면 {buildHasVcast
                ? 'UT/IT 함수별 커버리지·함수콜·함수 진입·모듈 드릴다운·복잡도×커버리지 산포도'
                : 'VectorCAST 시험·커버리지 전체'}가 아래 모든 섹션(유닛/통합테스트·커버리지·복잡도)에 채워집니다.
              <span className="text-muted"> 빌드 캐시 또는 SCM 로그에서 파싱 — Jenkins 라이브 연결 불필요.</span>
            </div>
            <button className="btn-primary" onClick={loadScmVcast} disabled={scmVcastLoading}
              title="UT/IT 함수레벨 데이터를 한 번에 불러옵니다(빌드 캐시/SCM 로그 파싱, Jenkins 연결 불필요).">
              {scmVcastLoading ? <span className="spinner" /> : (buildHasVcast ? '함수레벨 상세 불러오기' : 'SCM 경로에서 불러오기')}
            </button>
          </div>
        </div>
      )}

      {/* ── 정적분석 (Static Analysis · Helix QAC/PRQA, MISRA-C) ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">정적분석 (Helix QAC · MISRA-C)</span>
          {prqa.rule_violation_count != null && <SourceBadge source="jenkins" />}
        </div>
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          Helix QAC(PRQA) MISRA-C 정적분석 결과입니다. <b>준수율</b>=규칙 대비 적합 비율(90% 미만 경고),{' '}
          <b>위반 건수</b>=규칙 위반 총량, <b>위반/전체 규칙</b>=위반된 규칙 종류, <b>진단 수</b>=개별 진단 메시지,{' '}
          <b>HIS Metrics</b>=함수 순환복잡도(VG, 출처: Helix QAC). CodeSonar(PDF)·SonarQube는 현재 미연결입니다.
        </div>
        {/* 코드 규모 — 구 '코드 메트릭' 패널에서 이동. lizard(complexity.csv) 우선, 빌드에 없으면 QAC 폴백.
            source로 출처를 명시(QAC LOC은 헤더 포함이라 lizard NLOC과 값·의미가 다름). 완전 부재 시엔
            카드를 숨기지 않고 사유를 설명한다(과거 조용히 사라져 '왜 안나오지'를 유발했다). */}
        {(cm.code_files != null || cm.functions != null || cm.nloc != null) ? (
          <div style={{ marginBottom: 12 }}>
            <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>
              📏 코드 규모 {cm.source === 'qac' ? '(출처: Helix QAC)' : '(lizard 정적계수)'} — 파일·함수·라인
            </div>
            <div className="stats-row" style={{ marginBottom: 6 }}>
              {cm.code_files != null && <div className="stat-card"><div className="stat-value">{cm.code_files}</div><div className="stat-label">소스 파일</div></div>}
              {cm.functions != null && <div className="stat-card"><div className="stat-value">{cm.functions}</div><div className="stat-label">{cm.source === 'qac' ? '함수 (QAC HIS)' : '함수 수 (lizard 정적계수)'}</div></div>}
              {cm.nloc != null && <div className="stat-card"><div className="stat-value">{cm.nloc.toLocaleString()}</div><div className="stat-label">{cm.source === 'qac' ? 'LOC (QAC · 헤더 포함)' : 'NLOC'}</div></div>}
            </div>
            {cm.source === 'qac' && (
              <div className="text-muted" style={{ fontSize: 10 }}>
                * 이 빌드엔 lizard/VectorCAST 산출물이 없어 Helix QAC 리포트 값으로 대체했습니다(QAC LOC은 헤더 포함이라 lizard NLOC보다 큽니다).
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ marginBottom: 12, padding: 8, background: 'var(--bg)', borderRadius: 6, lineHeight: 1.5 }}>
            📏 코드 규모 — 이 빌드엔 <b>lizard/VectorCAST 커버리지 산출물</b>도 <b>Helix QAC 리포트</b>도 없어 집계할 수 없습니다.
            (VectorCAST가 SCM 소스인 경우 함수레벨 상세를 로드해도 빌드 산출물엔 포함되지 않습니다.)
          </div>
        )}
        {prqa.rule_violation_count != null ? (<>
          {prqa.project_compliance_index != null && (
            <div style={{ marginBottom: 10 }}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                <span className="text-sm" style={{ fontWeight: 600 }}>프로젝트 준수율</span>
                <span style={{ fontWeight: 700, color: prqa.project_compliance_index >= 90 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {prqa.project_compliance_index}%
                </span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: '#e5e7eb', overflow: 'hidden' }}>
                <div style={{ width: `${prqa.project_compliance_index}%`, height: '100%', borderRadius: 4,
                  background: prqa.project_compliance_index >= 90 ? 'var(--color-success)' : prqa.project_compliance_index >= 70 ? 'var(--color-warning)' : 'var(--color-danger)' }} />
              </div>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10 }}>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: prqa.rule_violation_count > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{prqa.rule_violation_count}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반 건수</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.violated_rules ?? '-'}<span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>/{(prqa.violated_rules ?? 0) + (prqa.compliant_rules ?? 0)}</span></div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반/전체 규칙</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.file_compliance_index ?? '-'}%</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>파일 준수율</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.diagnostic_count ?? '-'}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>진단 수</div>
            </div>
          </div>
          {Array.isArray(prqa.top_rules) && prqa.top_rules.length > 0 && (
            <details open style={{ marginBottom: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>위반 상위 규칙 ({prqa.top_rules.length})</summary>
              <div style={{ maxHeight: 220, overflowY: 'auto', marginTop: 6 }}>
                <table className="impact-table" style={{ fontSize: 10 }}>
                  <thead><tr><th>규칙</th><th>위반 수</th></tr></thead>
                  <tbody>
                    {prqa.top_rules.slice(0, 20).map((r, i) => (
                      <tr key={i}>
                        <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{r.rule ?? r.name ?? '-'}</td>
                        <td style={{ textAlign: 'center', fontWeight: 600 }}>{r.count ?? r.violations ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {Array.isArray(prqa.top_files) && prqa.top_files.length > 0 && (
            <details open style={{ marginBottom: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>위반 상위 파일 ({prqa.top_files.length})</summary>
              <div style={{ maxHeight: 220, overflowY: 'auto', marginTop: 6 }}>
                <table className="impact-table" style={{ fontSize: 10 }}>
                  <thead><tr><th>파일</th><th>위반 수</th><th>위반 규칙</th><th>준수율</th></tr></thead>
                  <tbody>
                    {prqa.top_files.slice(0, 20).map((f, i) => (
                      <tr key={i}>
                        <td className="text-sm" title={(f.path || (f.file ? '특정 파일에 귀속되지 않은 위반 (분석 카테고리)' : undefined))} style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontStyle: f.path ? 'normal' : 'italic', color: f.path ? undefined : 'var(--text-muted)' }}>{f.file ?? f.path ?? f.name ?? '-'}</td>
                        <td style={{ textAlign: 'center', fontWeight: 600 }}>{f.count ?? f.violations ?? '-'}</td>
                        <td style={{ textAlign: 'center' }}>{f.violated_rules ?? '-'}</td>
                        <td style={{ textAlign: 'center' }}>{f.compliance_index ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {/* 위반 상세 — 파일 × 규칙 매트릭스(WorstRules). "어떤 파일에서 어떤 MISRA 규칙이 몇 건"까지 드릴다운.
              함수/라인 단위는 QAC RCR에 없어(파일 레벨이 최대 granularity) 파일×규칙이 최상세. */}
          {Array.isArray(prqa.violations_by_file) && prqa.violations_by_file.length > 0 && (
            <details open style={{ marginBottom: 10 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                위반 상세 — 파일별 규칙 위반 내역 ({prqa.violations_by_file.length} 파일{prqa.violations_files_truncated_to ? ` · 상위 ${prqa.violations_files_truncated_to}개만` : ''})
              </summary>
              <div className="text-muted" style={{ fontSize: 10, margin: '4px 0 2px' }}>
                각 소스 파일에서 위반된 MISRA 규칙과 건수입니다 (출처: Helix QAC RCR · 파일 레벨).
                합계는 FileStatus 위반수(권위)이며, WorstRules에 없는 규칙은 "기타 규칙 (비상위)"로 표기됩니다.
              </div>
              {prqa.violations_attributed_total != null
                && (prqa.filestatus_total_vc ?? prqa.rule_violation_count) != null
                && ((prqa.filestatus_total_vc ?? prqa.rule_violation_count) - prqa.violations_attributed_total) > 0 && (
                <div style={{ fontSize: 10, margin: '2px 0 4px', color: 'var(--color-warning)' }}>
                  ⚠ 미귀속 위반 {Math.round((prqa.filestatus_total_vc ?? prqa.rule_violation_count) - prqa.violations_attributed_total)}건 —
                  원본 총계({Math.round(prqa.filestatus_total_vc ?? prqa.rule_violation_count)})가 파일별 위반 합계({prqa.violations_attributed_total})를 초과합니다.
                  원본 Helix QAC RCR 총계가 파일별 분해 합보다 큰 것으로, 그 차이는 아래 표에 나타나지 않습니다.
                </div>
              )}
              <div style={{ maxHeight: 320, overflowY: 'auto', marginTop: 4 }}>
                <table className="impact-table" style={{ fontSize: 10 }}>
                  <thead><tr><th>파일</th><th>위반 규칙 (건수)</th><th>합계</th></tr></thead>
                  <tbody>
                    {prqa.violations_by_file.map((f, i) => (
                      <tr key={i} style={{ background: f.total >= 50 ? '#fee2e2' : f.total >= 10 ? '#fef9c3' : undefined }}>
                        <td title={f.path || '특정 파일에 귀속되지 않은 위반 (분석 카테고리)'} style={{ fontFamily: 'monospace', fontSize: 10, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontStyle: f.path ? 'normal' : 'italic', color: f.path ? undefined : 'var(--text-muted)' }}>{f.file}</td>
                        <td style={{ fontSize: 10, lineHeight: 1.7 }}>
                          {(f.rules || []).map((r, j) => (
                            <span key={j} title={r.residual ? 'WorstRules(상위 규칙)에 포함되지 않은 나머지 위반 — 개별 규칙 미상세' : undefined} style={{ display: 'inline-block', margin: '1px 3px 1px 0', padding: '0 5px', borderRadius: 8, background: 'var(--bg)', border: r.residual ? '1px dashed var(--border, #d1d5db)' : '1px solid var(--border, #d1d5db)', whiteSpace: 'nowrap', fontStyle: r.residual ? 'italic' : 'normal', color: r.residual ? 'var(--text-muted)' : undefined }}>
                              {r.rule} <b>{r.count}</b>
                            </span>
                          ))}
                        </td>
                        <td style={{ textAlign: 'center', fontWeight: 700 }}>{f.total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {hmr.functions_total && (
            <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>HIS Metrics (복잡도 · 출처: Helix QAC)</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.functions_total}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>분석 함수 (QAC HIS)</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: hmr.vg_max > threshold ? 'var(--color-danger)' : 'var(--color-success)' }}>{hmr.vg_max}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG Max</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.vg_p95}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG P95</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.vg_mean?.toFixed(1)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG 평균</div>
                </div>
              </div>
            </div>
          )}
        </>) : (
          <div className="text-muted text-sm" style={{ padding: 8, lineHeight: 1.5 }}>
            {prqa.rcr_ok === false ? (
              <>이 빌드의 PRQA(Helix QAC) RCR 리포트를 <b>파싱하지 못했습니다</b>
                {prqa.rcr_reason ? <> (사유: <code>{prqa.rcr_reason}</code>)</> : null}. 리포트 파일 형식/손상을 확인하세요.</>
            ) : (
              <>이 빌드 산출물에 PRQA(Helix QAC) 정적분석 결과가 <b>없습니다</b>. Jenkins 빌드의 PRQA HMR/RCR 리포트가 필요합니다.</>
            )}
            {' '}(CodeSonar는 아래에서 SCM 정적분석 PDF로 불러올 수 있습니다.)
          </div>
        )}

        {/* ── SCM 정적분석 도구 4종 (CodeSonar/QAC HIS/CPD/CodeEye · PDF·XML) ── */}
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexWrap: 'wrap', gap: 6 }}>
            <span className="text-sm" style={{ fontWeight: 700 }}>SCM 정적분석 도구 (CodeSonar · QAC · CPD · CodeEye)</span>
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              {sa?.ok && <SourceBadge source="scm" />}
              {!sa?.ok && codesonarPaths.length > 0 && (
                <button className="btn-sm" onClick={loadStaticAnalysis} disabled={saLoading}
                  title="SCM 정적분석 폴더에서 CodeSonar/CPD/QAC/CodeEye 최신 리포트를 불러옵니다(cloudium read).">
                  {saLoading ? <span className="spinner" /> : '정적분석 불러오기'}
                </button>
              )}
            </div>
          </div>
          <div className="text-sm text-muted" style={{ padding: '0 0 6px', lineHeight: 1.5 }}>
            SCM에 올라간 정적분석 4종 산출물(PDF·XML)에서 요약을 추출합니다 — <b>CodeSonar</b>(런타임 오류·데이터플로우),{' '}
            <b>QAC HIS</b>(함수 복잡도 v(G)), <b>CPD</b>(코드 중복), <b>CodeEye</b>(OSS 라이선스). 빌드 PRQA와 별개의 SCM 원본입니다.
          </div>
          {!sa && codesonarPaths.length === 0 && (
            <div className="text-sm text-muted">정적분석 경로 미등록 — 설정 &gt; SCM 연결 문서 경로에 정적분석 폴더(예: …/09.정적분석/01.Static Analysis)를 등록하면 불러올 수 있습니다.</div>
          )}
          {sa && !sa.ok && (
            <div className="text-sm text-muted">정적분석 결과를 찾지 못했습니다: {sa.detail || '알 수 없음'}</div>
          )}
          {Array.isArray(sa?.warnings) && sa.warnings.length > 0 && (
            <div className="text-muted" style={{ fontSize: 10, marginBottom: 8, padding: '4px 8px',
              background: 'var(--accent-soft, #fef9c3)', color: 'var(--text)', borderRadius: 4 }}>
              ⓘ 일부 산출물이 제외됐습니다: {sa.warnings.join(' · ')}
            </div>
          )}

          {/* CodeSonar (모듈별 APP/BOOT) */}
          {sa?.codesonar?.ok && (
            <div style={{ marginBottom: 12 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>🔍 CodeSonar — 런타임 오류·데이터플로우</div>
              {saModules(sa.codesonar).map((m, i) => <SaCodeSonarModule key={m.label || i} m={m} />)}
            </div>
          )}

          {/* QAC HIS Metrics (모듈별 APP/BOOT) */}
          {sa?.qac?.ok && (
            <div style={{ marginBottom: 12 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>📐 QAC HIS Metrics (Helix QAC) — 함수 순환복잡도 v(G)</div>
              {saModules(sa.qac).map((m, i) => <SaQacModule key={m.label || i} m={m} threshold={threshold} />)}
            </div>
          )}

          {/* CPD (모듈별 APP/BOOT) */}
          {sa?.cpd?.ok && (
            <div style={{ marginBottom: 12 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>📋 CPD (Copy-Paste Detection) — 코드 중복</div>
              {saModules(sa.cpd).map((m, i) => <SaCpdModule key={m.label || i} m={m} />)}
            </div>
          )}

          {/* CodeEye (모듈별 APP/BOOT) */}
          {sa?.codeeye?.ok && (
            <div>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>📜 CodeEye — OSS 라이선스 검사</div>
              {saModules(sa.codeeye).map((m, i) => <SaCodeEyeModule key={m.label || i} m={m} />)}
            </div>
          )}
        </div>
      </div>

      {/* ── 유닛테스트 (Unit Test · VectorCAST UT) ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">유닛테스트 (Unit Test · VectorCAST UT)</span>
          {vcastSource && <SourceBadge source={vcastSource} />}
        </div>
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          VectorCAST 단위시험(UT) 결과입니다. <b>테스트 케이스</b>=UT 시험 수, <b>UT 리포트</b>=리포트 폴더 수,{' '}
          <b>통과·실패·통과율</b>=단위시험(UT) 합부, <b>Statement/Branch Coverage</b>=단위시험 구문·분기 커버리지.{' '}
          ‘함수레벨 상세 불러오기’를 누르면 구문/분기/MC/DC 함수 entries가 채워집니다. 시험 합격·커버리지 목표는 프로젝트 Safety Plan과 시험 완료 기준을 따릅니다.
        </div>
        {!buildHasVcast && !scmVcast && (
          <div className="text-sm text-muted" style={{ marginBottom: 6 }}>
            {scmVcastPaths.length > 0
              ? '이 빌드 산출물에 VectorCAST 결과가 없습니다. SCM에 등록한 경로에서 불러오려면 위 버튼을 클릭하세요.'
              : '이 빌드 산출물에 VectorCAST 결과가 없습니다. (설정 > SCM 연결 문서 경로에 VectorCAST 로그 폴더를 등록하면 불러올 수 있습니다.)'}
          </div>
        )}
        <div className="stats-row">
          {utTcCount != null && (
            <div className="stat-card"><div className="stat-value">{utTcCount.toLocaleString()}</div><div className="stat-label">테스트 케이스</div></div>
          )}
          <div className="stat-card"><div className="stat-value">{(effVcast.ut_reports || []).length}</div><div className="stat-label">UT 리포트</div></div>
          {tester?.vectorcast_ut_line_rate != null && (
            <div className="stat-card"><div className="stat-value" style={{ color: tester.vectorcast_ut_line_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{tester.vectorcast_ut_line_rate.toFixed(1)}%</div><div className="stat-label">UT Statement Rate</div></div>
          )}
          {tester?.vectorcast_ut_branch_rate != null && (
            <div className="stat-card"><div className="stat-value" style={{ color: tester.vectorcast_ut_branch_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{tester.vectorcast_ut_branch_rate.toFixed(1)}%</div><div className="stat-label">UT Branch Rate</div></div>
          )}
        </div>
        {scmCovUt && (scmCovUt.statement?.total || scmCovUt.branch?.total || scmCovUt.mcdc?.total) ? (
          <div className="stats-row" style={{ marginTop: 8 }}>
            {covCard('UT 구문(Statement)', scmCovUt.statement)}
            {covCard('UT 분기(Branch)', scmCovUt.branch)}
            {covCard('UT MC/DC', scmCovUt.mcdc)}
          </div>
        ) : (utCov.line_covered != null && (
          <div className="stats-row" style={{ marginTop: 8 }}>
            <div className="stat-card"><div className="stat-value">{utCov.line_covered?.toLocaleString()}<span style={{ fontSize: 11, fontWeight: 400 }}>/{utCov.line_total?.toLocaleString()}</span></div><div className="stat-label">UT 구문</div></div>
            {utCov.branch_covered != null && <div className="stat-card"><div className="stat-value">{utCov.branch_covered?.toLocaleString()}<span style={{ fontSize: 11, fontWeight: 400 }}>/{utCov.branch_total?.toLocaleString()}</span></div><div className="stat-label">UT 분기</div></div>}
          </div>
        ))}
        {utEntries.length > 0 && (
          <div className="text-sm text-muted" style={{ marginTop: 6 }}>
            UT 함수 {utEntries.length.toLocaleString()}개 — 함수별 커버리지는 아래 ‘모듈별 커버리지 (UT)’ 표의 모듈 행을 펼쳐 확인하세요.
          </div>
        )}
        {utSummary && (utSummary.total || 0) > 0 && (
          ((utSummary.passed ?? 0) + (utSummary.failed ?? 0) > 0) ? (
            <>
            <div className="stats-row" style={{ marginTop: 8 }}>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}>
                <div className="stat-value" style={{ color: 'var(--color-success)' }}>{(utSummary.passed ?? 0).toLocaleString()}</div>
                <div className="stat-label">통과 ({utLabelSuffix})</div>
              </div>
              <div className="stat-card" style={{ borderLeft: `3px solid ${(utSummary.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
                <div className="stat-value" style={{ color: (utSummary.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{(utSummary.failed ?? 0).toLocaleString()}</div>
                <div className="stat-label">실패 ({utLabelSuffix})</div>
              </div>
              {/* 2026-07-23 — 스킵·미분류는 0이어도 항상 표시(0건임을 확인 가능하게, 은폐 방지) */}
              <div className="stat-card">
                <div className="stat-value" style={{ color: (utSummary.skipped ?? 0) > 0 ? undefined : 'var(--text-muted)' }}>{(utSummary.skipped ?? 0).toLocaleString()}</div><div className="stat-label">스킵</div>
              </div>
              <div className="stat-card" title="통과·실패·스킵 어디에도 분류되지 않은 케이스(원본 결과 문자열 미인식) — 0으로 임의 처리하지 않고 표면화">
                <div className="stat-value" style={{ color: (utSummary.unknown ?? 0) > 0 ? 'var(--color-warning)' : 'var(--text-muted)' }}>{(utSummary.unknown ?? 0).toLocaleString()}</div><div className="stat-label">미분류</div>
              </div>
              {utSummary.pass_rate != null && (
                <div className="stat-card" title="통과율 = 통과 / 전체(스킵·미분류 포함)" style={{ borderLeft: `3px solid ${utSummary.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
                  <div className="stat-value" style={{ color: utSummary.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{Math.round(utSummary.pass_rate * 100)}%</div>
                  <div className="stat-label">통과율 ({utLabelSuffix})</div>
                </div>
              )}
            </div>
            <div className="text-muted" style={{ fontSize: 9, marginTop: 2, lineHeight: 1.5 }}>
              통과율=통과/전체(스킵·미분류 포함). 전체 = 통과+실패+스킵+미분류. 원본 결과는 통과/실패/스킵/미분류로 정규화됩니다 — 실행오류(ERROR)는 실패, 미실행(NOT RUN)은 스킵으로 집계되고, 인식 불가 결과만 미분류입니다.
              {(() => {
                const _t = utSummary.total ?? 0;
                const _s = (utSummary.passed ?? 0) + (utSummary.failed ?? 0) + (utSummary.skipped ?? 0) + (utSummary.unknown ?? 0);
                return _t === _s ? null : (
                  <span style={{ color: 'var(--color-warning)', fontWeight: 700 }}> ⚠ 시험 상태 합계({_s.toLocaleString()})가 전체 테스트 케이스({_t.toLocaleString()})와 일치하지 않습니다.</span>
                );
              })()}
            </div>
            </>
          ) : (
            // 결과 전부 미분류(result=None) — 빌드 산출물 VectorCAST가 '커버리지 기준'이라 per-testcase 합부가 없음.
            // '통과 0/실패 0/통과율 0%'는 오해 소지 → 미분류임을 명시(빌드 자체는 성공).
            <div className="text-sm text-muted" style={{ marginTop: 8, padding: 8, background: 'var(--bg)', borderRadius: 6, lineHeight: 1.55 }}>
              이 빌드 산출물의 VectorCAST 데이터는 <b>커버리지 기준</b>(함수별 구문/분기/함수콜)이라 개별 시험 합부(pass/fail)가 없습니다 —
              총 <b>{(utSummary.total ?? 0).toLocaleString()}</b>건이 결과 미분류이며, <b>빌드 자체는 성공</b>입니다(통과율 0%는 실패가 아니라 미분류).
              개별 시험 합부는 SCM의 VectorCAST 시험 로그(SwUTR/SwITR)에 있습니다.
            </div>
          )
        )}
        {utFailures.length > 0 && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--color-danger)' }}>
              실패 테스트케이스 ({utFailures.length}건, {utLabelSuffix})
            </summary>
            <div style={{ maxHeight: 250, overflowY: 'auto', marginTop: 6 }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead><tr><th>테스트케이스</th><th>함수(subprogram)</th><th>유닛</th><th>결과</th></tr></thead>
                <tbody>
                  {utFailures.slice(0, 100).map((f, i) => (
                    <tr key={i} style={{ background: '#fee2e2' }}>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.testcase ?? '-'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.subprogram ?? '-'}</td>
                      <td className="text-sm" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.unit ?? '-'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }} title="원본 결과 문자열 — 실행오류(ERROR)와 검증실패(FAIL) 구분용">{f.result ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {utFailures.length > 100 && <div className="text-muted text-sm" style={{ padding: 6, textAlign: 'center' }}>{utFailures.length - 100}건 더 있음</div>}
          </details>
        )}
        {/* ── UT 모듈별 커버리지 (단위시험 함수만 — 과거 'UT+IT 합산 커버리지 상세'를 UT 전용으로 분리) ── */}
        {coverageModulesUt.length > 0 && (
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
            <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>📊 모듈별 커버리지 (UT)</div>
            <div className="text-sm text-muted" style={{ marginBottom: 8, lineHeight: 1.5 }}>
              <b>구문</b>=실행 문장, <b>분기</b>=if·switch 등 제어 경로, <b>MC/DC</b>=복합 결정문의 각 개별 조건이 결정 결과에 독립적으로 영향을 주는지 확인하는 커버리지(적용 목표는 대상 ASIL·Safety Plan 기준).{' '}
              모듈 표의 <b>행을 클릭</b>하면 단위시험(UT) 함수별 커버리지로 펼쳐집니다.
            </div>
            <details style={{ marginTop: 8 }} open>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                모듈별 커버리지 ({coverageModulesUt.length}개, 파일/유닛 단위){fnLevelLoaded ? ' — 행 클릭 시 함수별 펼침' : ' (함수 드릴다운은 함수레벨 상세 로드 후)'}
              </summary>
              <div style={{ maxHeight: 360, overflowY: 'auto', marginTop: 6 }}>
                <table className="impact-table" style={{ fontSize: 10 }}>
                  <thead><tr><th>모듈</th><th>구문(Statement)</th><th>분기(Branch)</th><th></th></tr></thead>
                  <tbody>
                    {coverageModulesUt.map((m) => (
                      <ModuleCovRow key={m.name} name={m.name} lineRate={m.lineRate} branchRate={m.branchRate} functions={m.functions} />
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        )}
        {/* ── SwUTCV 정합성 검증 (Coverage Report ↔ SUTR) ── */}
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
            🔍 정합성 검증 (SwUTCV Coverage ↔ SUTR){utcvReport ? (utcvReport.ok ? ' — ✅ PASS' : ' — ⚠️ FAIL') : ''}
          </summary>
          <div style={{ marginTop: 8 }}>
            <div className="text-sm text-muted" style={{ marginBottom: 8, lineHeight: 1.5 }}>
              생성한 <b>SwUTCV Coverage(.xlsx)</b> / <b>SUTR(.xlsm)</b> 경로를 지정해, 문서 하나만 <b>‘이 문서 파싱’</b>하면 그 산출물 결과(미커버 함수·Exception·통과/실패 등)를, 둘 다 넣고 <b>‘정합성 비교’</b>하면 Coverage↔SUTR 교차검증까지 표시합니다.
            </div>
            <PathRow label="Coverage(.xlsx)" value={utcvForm.coverage_path}
              onChange={v => setUtcvForm(f => ({ ...f, coverage_path: v }))}
              onBrowse={() => openPicker({ pattern: '*.xlsx', title: 'SwUTCV Coverage Report 선택', current: utcvForm.coverage_path, onSelect: p => setUtcvForm(f => ({ ...f, coverage_path: p })) })}
              isAdmin={isAdmin} browseTitle={browseDisabledTitle} placeholder="…/SwUTCV_Coverage_*.xlsx" />
            <button type="button" className="btn-secondary" style={{ fontSize: 11, marginBottom: 6 }}
              disabled={!!utDocBusy || !utcvForm.coverage_path}
              onClick={() => parseDoc('swut', 'coverage', utcvForm.coverage_path)}>
              {utDocBusy === 'coverage' ? '파싱 중...' : '📄 이 문서 파싱 (Coverage)'}
            </button>
            {utDoc.coverage && utDoc.coverage._path === utcvForm.coverage_path
              && <ConsistencyResult report={utDoc.coverage} peerLabel="SUTR" hideVerdict />}
            <PathRow label="SUTR(.xlsm)" value={utcvForm.sutr_path}
              onChange={v => setUtcvForm(f => ({ ...f, sutr_path: v }))}
              onBrowse={() => openPicker({ pattern: '*.xlsm', title: 'SUTR 선택', current: utcvForm.sutr_path, onSelect: p => setUtcvForm(f => ({ ...f, sutr_path: p })) })}
              isAdmin={isAdmin} browseTitle={browseDisabledTitle} placeholder="…/SUTR_*.xlsm" />
            <button type="button" className="btn-secondary" style={{ fontSize: 11, marginBottom: 6 }}
              disabled={!!utDocBusy || !utcvForm.sutr_path}
              onClick={() => parseDoc('swut', 'report', utcvForm.sutr_path)}>
              {utDocBusy === 'report' ? '파싱 중...' : '📄 이 문서 파싱 (SUTR)'}
            </button>
            {utDoc.report && utDoc.report._path === utcvForm.sutr_path
              && <ConsistencyResult report={utDoc.report} peerLabel="SUTR" hideVerdict />}
            <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
            <button type="button" className="btn-primary"
              disabled={utcvChecking || !utcvForm.coverage_path || !utcvForm.sutr_path}
              onClick={runUtcvCheck} style={{ fontSize: 12 }}>
              {utcvChecking ? '검증 중...' : '🔍 정합성 비교 (두 문서)'}
            </button>
            <ConsistencyResult report={utcvReport} peerLabel="SUTR" />
          </div>
        </details>
      </div>

      {/* ── 통합테스트 (Integration Test · VectorCAST IT) ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">통합테스트 (Integration Test · VectorCAST IT)</span>
          {vcastSource && <SourceBadge source={vcastSource} />}
        </div>
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          VectorCAST 통합시험(IT) 결과입니다. 통합시험의 주요 구조 커버리지는 <b>Function Coverage</b>와 <b>Call Coverage</b>이며,{' '}
          IT 실행 과정에서 확보된 Statement·Branch·MC/DC는 실행 코드 커버리지 보조 지표로 제공합니다.{' '}
          <b>IT 리포트</b>=리포트 폴더 수, <b>함수콜(Call)</b>=호출 커버리지, <b>함수 커버리지(Function)</b>=함수 진입 커버리지, <b>통과·실패·통과율</b>=통합시험(IT) 합부.{' '}
          함수콜 데이터는 <b>Jenkins 빌드 산출물</b> 또는 <b>SCM VectorCAST 로그</b>(폴더에 Metric report HTML이 있을 때)에서 제공됩니다.{' '}
          <span style={{ color: 'var(--color-warning)' }}>※ <b>Function Coverage</b>의 분모는 분석 대상 함수 수, <b>Call Coverage</b>의 분모는 VectorCAST Metric Report에서 식별된 호출 지점(Function Calls) 수입니다. 시험 대상 함수만 집계하는 SwITCV/SITR 산출물과는 모집단(분모)이 달라 수치가 일치하지 않을 수 있습니다. 복수 SCM 폴더(APP+BOOT 등)를 합산하면 공유 함수/호출 관계가 중복 계상되어 커버리지 비율이 왜곡될 수 있으니, 공식 판정에는 소스 경로·함수 식별자·호출 관계 기준으로 중복 제거한 결과를 사용해야 합니다.</span>
        </div>
        <div className="stats-row">
          <div className="stat-card"><div className="stat-value">{(effVcast.it_reports || []).length}</div><div className="stat-label">IT 리포트</div></div>
          {tester?.vectorcast_it_line_rate != null && (
            <div className="stat-card"><div className="stat-value" style={{ color: tester.vectorcast_it_line_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{tester.vectorcast_it_line_rate.toFixed(1)}%</div><div className="stat-label">IT Statement Rate</div></div>
          )}
          {tester?.vectorcast_it_branch_rate != null && (
            <div className="stat-card"><div className="stat-value" style={{ color: tester.vectorcast_it_branch_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{tester.vectorcast_it_branch_rate.toFixed(1)}%</div><div className="stat-label">IT Branch Rate</div></div>
          )}
          {itGrand.function_calls?.total ? (
            <div className="stat-card" style={{ borderLeft: `3px solid ${pctOf(itGrand.function_calls) >= 80 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
              <div className="stat-value" style={{ color: pctOf(itGrand.function_calls) >= 80 ? 'var(--color-success)' : 'var(--color-warning)' }}>{pctOf(itGrand.function_calls)}%</div>
              <div className="stat-label">함수콜 커버리지 (Call Coverage)</div>
              <div className="text-muted" style={{ fontSize: 9 }}>{itGrand.function_calls.covered?.toLocaleString()}/{itGrand.function_calls.total?.toLocaleString()} ({((itGrand.function_calls.rate ?? itGrand.function_calls.covered / itGrand.function_calls.total) * 100).toFixed(2)}%)</div>
              <div className="text-muted" style={{ fontSize: 9 }}>미커버 호출 {((itGrand.function_calls.total ?? 0) - (itGrand.function_calls.covered ?? 0)).toLocaleString()}</div>
            </div>
          ) : null}
          {itGrand.functions?.total ? (
            <div className="stat-card">
              <div className="stat-value">{pctOf(itGrand.functions)}%</div>
              <div className="stat-label">함수 커버리지 (Function Coverage)</div>
              <div className="text-muted" style={{ fontSize: 9 }}>{itGrand.functions.covered?.toLocaleString()}/{itGrand.functions.total?.toLocaleString()} ({((itGrand.functions.rate ?? itGrand.functions.covered / itGrand.functions.total) * 100).toFixed(2)}%)</div>
              <div className="text-muted" style={{ fontSize: 9 }}>미커버 함수 {((itGrand.functions.total ?? 0) - (itGrand.functions.covered ?? 0)).toLocaleString()}</div>
            </div>
          ) : null}
          {/* 2026-07-23 (2.1) — 함수레벨 로드됐는데 Metric Report(함수/호출 커버리지)가 없으면
              카드가 침묵 소멸하던 것 → 원본 데이터 부재를 명시(설명문이 약속한 지표의 정직 처리). */}
          {itEntries.length > 0 && !itGrand.function_calls?.total && !itGrand.functions?.total && (
            <div className="stat-card" style={{ borderLeft: '3px solid var(--text-muted)' }}>
              <div className="stat-value" style={{ color: 'var(--text-muted)', fontSize: 14 }}>—</div>
              <div className="stat-label">Function/Call Coverage</div>
              <div className="text-muted" style={{ fontSize: 9 }}>원본 데이터 없음 (Metric Report 미확인)</div>
            </div>
          )}
        </div>
        {sumIt && (sumIt.total || 0) > 0 && ((sumIt.passed ?? 0) + (sumIt.failed ?? 0) > 0) && (
          <>
          <div className="stats-row" style={{ marginTop: 8 }}>
            {itTcCount != null && (
              <div className="stat-card"><div className="stat-value">{itTcCount.toLocaleString()}</div><div className="stat-label">테스트 케이스 (IT)</div></div>
            )}
            <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}>
              <div className="stat-value" style={{ color: 'var(--color-success)' }}>{(sumIt.passed ?? 0).toLocaleString()}</div>
              <div className="stat-label">통과 (IT)</div>
            </div>
            <div className="stat-card" style={{ borderLeft: `3px solid ${(sumIt.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
              <div className="stat-value" style={{ color: (sumIt.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{(sumIt.failed ?? 0).toLocaleString()}</div>
              <div className="stat-label">실패 (IT)</div>
            </div>
            {/* 2026-07-23 (2.3) — 스킵·미분류는 0이어도 항상 표시(0건 확인 가능하게, 은폐 방지) */}
            <div className="stat-card">
              <div className="stat-value" style={{ color: (sumIt.skipped ?? 0) > 0 ? undefined : 'var(--text-muted)' }}>{(sumIt.skipped ?? 0).toLocaleString()}</div><div className="stat-label">스킵</div>
            </div>
            <div className="stat-card" title="통과·실패·스킵 어디에도 분류되지 않은 케이스(원본 결과 문자열 미인식) — 0으로 임의 처리하지 않고 표면화">
              <div className="stat-value" style={{ color: (sumIt.unknown ?? 0) > 0 ? 'var(--color-warning)' : 'var(--text-muted)' }}>{(sumIt.unknown ?? 0).toLocaleString()}</div><div className="stat-label">미분류</div>
            </div>
            {sumIt.pass_rate != null && (
              <div className="stat-card" title="통과율 = 통과 / 전체(스킵·미분류 포함)" style={{ borderLeft: `3px solid ${sumIt.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
                <div className="stat-value" style={{ color: sumIt.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{Math.round(sumIt.pass_rate * 100)}%</div>
                <div className="stat-label">통과율 (IT)</div>
              </div>
            )}
          </div>
          <div className="text-muted" style={{ fontSize: 9, marginTop: 2, lineHeight: 1.5 }}>
            통과율=통과/전체(스킵·미분류 포함). 전체 = 통과+실패+스킵+미분류. 원본 결과는 통과/실패/스킵/미분류로 정규화됩니다 — 실행오류(ERROR)는 실패, 미실행(NOT RUN)은 스킵으로 집계되고, 인식 불가 결과만 미분류입니다(UT와 동일 규칙).
            {(() => {
              const _t = sumIt.total ?? 0;
              const _s = (sumIt.passed ?? 0) + (sumIt.failed ?? 0) + (sumIt.skipped ?? 0) + (sumIt.unknown ?? 0);
              return _t === _s ? null : (
                <span style={{ color: 'var(--color-warning)', fontWeight: 700 }}> ⚠ 시험 상태 합계({_s.toLocaleString()})가 전체 테스트 케이스({_t.toLocaleString()})와 일치하지 않습니다.</span>
              );
            })()}
          </div>
          </>
        )}
        {/* IT 결과 전부 미분류(coverage-only) — '통과 0/실패 0'을 실패로 오인 방지(UT 패널 안내와 대칭) */}
        {sumIt && (sumIt.total || 0) > 0 && ((sumIt.passed ?? 0) + (sumIt.failed ?? 0) === 0) && (
          <div className="text-sm text-muted" style={{ marginTop: 8, padding: 8, background: 'var(--bg)', borderRadius: 6, lineHeight: 1.55 }}>
            이 통합시험 데이터는 <b>커버리지 기준</b>(함수콜·구문/분기)이라 개별 시험 합부(pass/fail)가 없습니다 —
            총 <b>{(sumIt.total ?? 0).toLocaleString()}</b>건이 결과 미분류입니다. 개별 시험 합부는 SCM의 VectorCAST 시험 로그(SITR)에 있습니다.
          </div>
        )}
        {scmCovIt && (scmCovIt.statement?.total || scmCovIt.branch?.total || scmCovIt.mcdc?.total) ? (
          <>
          <div className="stats-row" style={{ marginTop: 8 }}>
            {covCard('IT 구문(Statement)', scmCovIt.statement)}
            {covCard('IT 분기(Branch)', scmCovIt.branch)}
            {covCard('IT MC/DC', scmCovIt.mcdc)}
            {/* 2026-07-23 (2.5) — MC/DC 미측정 명시. 과거엔 AggregateCoverage 3번째 컬럼(Functions,
                함수 진입)을 MC/DC 로 위치-오배정해 거짓 53%를 냈다. 백엔드가 헤더기반 매핑으로 고쳐
                실제 MC/DC 컬럼이 없으면 mcdc=0/0 → 카드 대신 '측정 안 됨' 명시(침묵 소멸·거짓 표기 방지). */}
            {!(scmCovIt.mcdc?.total) && (
              <div className="stat-card" style={{ borderLeft: '3px solid var(--text-muted)' }}>
                <div className="stat-value" style={{ color: 'var(--text-muted)', fontSize: 14 }}>—</div>
                <div className="stat-label">IT MC/DC</div>
                <div className="text-muted" style={{ fontSize: 9 }}>원본 리포트에서 측정 안 됨</div>
              </div>
            )}
          </div>
          <div className="text-muted" style={{ fontSize: 9, marginTop: 2, lineHeight: 1.5 }}>
            ※ 구문/분기{scmCovIt.mcdc?.total ? '/MC-DC' : ''}는 복수 SCM 폴더(APP+BOOT 등) 합산 시 공유 함수가 중복 계상되어 비율이 왜곡될 수 있습니다 — 공식 판정에는 중복 제거본을 사용하세요. MC/DC는 원본 AggregateCoverage에 실제 MC/DC 컬럼이 있을 때만 표시됩니다(함수 진입 커버리지를 MC/DC로 오표기하지 않음).
          </div>
          </>
        ) : null}
        {itFailures.length > 0 && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--color-danger)' }}>
              실패 테스트케이스 ({itFailures.length}건, IT)
            </summary>
            <div style={{ maxHeight: 250, overflowY: 'auto', marginTop: 6 }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead><tr><th>테스트케이스</th><th>함수(subprogram)</th><th>유닛</th><th>결과</th></tr></thead>
                <tbody>
                  {itFailures.slice(0, 100).map((f, i) => (
                    <tr key={i} style={{ background: '#fee2e2' }}>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.testcase ?? '-'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.subprogram ?? '-'}</td>
                      <td className="text-sm" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.unit ?? '-'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }} title="원본 결과 문자열 — 실행오류(ERROR)와 검증실패(FAIL) 구분용">{f.result ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {itFailures.length > 100 && <div className="text-muted text-sm" style={{ padding: 6, textAlign: 'center' }}>{itFailures.length - 100}건 더 있음</div>}
          </details>
        )}
        {/* ── IT 모듈별 커버리지 (통합시험 함수만 — 함수콜 중심 드릴다운) ── */}
        {coverageModulesIt.length > 0 && (
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
            <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>📊 모듈별 커버리지 (IT)</div>
            <div className="text-sm text-muted" style={{ marginBottom: 8, lineHeight: 1.5 }}>
              통합시험(IT)은 <b>함수 호출(Function Call)</b> 중심입니다. 모듈 표의 <b>행을 클릭</b>하면 IT 함수별 함수콜·커버리지로 펼쳐집니다.{' '}
              여기서 모듈은 <b>통합시험 대상 컴포넌트</b>(env/component) 단위라, 파일 단위로 집계되는 단위시험(UT)의 파일·유닛 수와 다를 수 있습니다. 실제 누락 여부는 원본 VectorCAST 환경 및 시험 대상 컴포넌트 목록과 대조하여 판단합니다.
            </div>
            <details style={{ marginTop: 8 }} open>
              <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                모듈별 커버리지 ({coverageModulesIt.length}개, 통합 컴포넌트 단위){fnLevelLoaded ? ' — 행 클릭 시 함수별 펼침' : ' (함수 드릴다운은 함수레벨 상세 로드 후)'}
              </summary>
              <div style={{ maxHeight: 360, overflowY: 'auto', marginTop: 6 }}>
                <table className="impact-table" style={{ fontSize: 10 }}>
                  <thead><tr><th>모듈</th><th>구문(Statement)</th><th>분기(Branch)</th><th></th></tr></thead>
                  <tbody>
                    {coverageModulesIt.map((m) => (
                      <ModuleCovRow key={m.name} name={m.name} lineRate={m.lineRate} branchRate={m.branchRate} functions={m.functions} />
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        )}
        {itEntries.length > 0 && coverageModulesIt.length === 0 && (
          <div className="text-sm text-muted" style={{ marginTop: 6 }}>
            IT 함수 {itEntries.length.toLocaleString()}개 — 모듈(unit) 정보가 없어 표로 묶지 못했습니다.
          </div>
        )}
        {!fnLevelLoaded && canLoadFnLevel && (
          <div className="text-sm text-muted" style={{ marginTop: 6, padding: 8, background: 'var(--bg)', borderRadius: 6, lineHeight: 1.5 }}>
            <b>함수콜·함수 진입 커버리지</b>와 IT 함수별 entries는 위쪽 <b>‘함수레벨 상세 불러오기’</b> 버튼을 누르면 표시됩니다
            (빌드 캐시에서 즉시 로드 — Jenkins 연결 불필요).
          </div>
        )}
        {!buildHasVcast && !scmVcast && !canLoadFnLevel && (
          <div className="text-sm text-muted" style={{ marginTop: 6 }}>통합시험 데이터가 없습니다.</div>
        )}
        {/* ── SwITCV 정합성 검증 (Coverage Report ↔ SITR) ── */}
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
            🔍 정합성 검증 (SwITCV Coverage ↔ SITR){itcvReport ? (itcvReport.ok ? ' — ✅ PASS' : ' — ⚠️ FAIL') : ''}
          </summary>
          <div style={{ marginTop: 8 }}>
            <div className="text-sm text-muted" style={{ marginBottom: 8, lineHeight: 1.5 }}>
              생성한 <b>SwITCV Coverage(.xlsx)</b> / <b>SITR(.xlsm)</b> 경로를 지정해, 문서 하나만 <b>‘이 문서 파싱’</b>하면 그 산출물 결과(미커버 함수·Exception·통과/실패 등)를, 둘 다 넣고 <b>‘정합성 비교’</b>하면 Coverage↔SITR 교차검증까지 표시합니다.
            </div>
            <PathRow label="Coverage(.xlsx)" value={itcvForm.coverage_path}
              onChange={v => setItcvForm(f => ({ ...f, coverage_path: v }))}
              onBrowse={() => openPicker({ pattern: '*.xlsx', title: 'SwITCV Coverage Report 선택', current: itcvForm.coverage_path, onSelect: p => setItcvForm(f => ({ ...f, coverage_path: p })) })}
              isAdmin={isAdmin} browseTitle={browseDisabledTitle} placeholder="…/SwITCV_Coverage_*.xlsx" />
            <button type="button" className="btn-secondary" style={{ fontSize: 11, marginBottom: 6 }}
              disabled={!!itDocBusy || !itcvForm.coverage_path}
              onClick={() => parseDoc('swit', 'coverage', itcvForm.coverage_path)}>
              {itDocBusy === 'coverage' ? '파싱 중...' : '📄 이 문서 파싱 (Coverage)'}
            </button>
            {itDoc.coverage && itDoc.coverage._path === itcvForm.coverage_path
              && <ConsistencyResult report={itDoc.coverage} peerLabel="SITR" hideVerdict />}
            <PathRow label="SITR(.xlsm)" value={itcvForm.sitr_path}
              onChange={v => setItcvForm(f => ({ ...f, sitr_path: v }))}
              onBrowse={() => openPicker({ pattern: '*.xlsm', title: 'SITR 선택', current: itcvForm.sitr_path, onSelect: p => setItcvForm(f => ({ ...f, sitr_path: p })) })}
              isAdmin={isAdmin} browseTitle={browseDisabledTitle} placeholder="…/SITR_*.xlsm" />
            <button type="button" className="btn-secondary" style={{ fontSize: 11, marginBottom: 6 }}
              disabled={!!itDocBusy || !itcvForm.sitr_path}
              onClick={() => parseDoc('swit', 'report', itcvForm.sitr_path)}>
              {itDocBusy === 'report' ? '파싱 중...' : '📄 이 문서 파싱 (SITR)'}
            </button>
            {itDoc.report && itDoc.report._path === itcvForm.sitr_path
              && <ConsistencyResult report={itDoc.report} peerLabel="SITR" hideVerdict />}
            <div style={{ borderTop: '1px solid var(--border)', margin: '8px 0' }} />
            <button type="button" className="btn-primary"
              disabled={itcvChecking || !itcvForm.coverage_path || !itcvForm.sitr_path}
              onClick={runItcvCheck} style={{ fontSize: 12 }}>
              {itcvChecking ? '검증 중...' : '🔍 정합성 비교 (두 문서)'}
            </button>
            <ConsistencyResult report={itcvReport} peerLabel="SITR" />
          </div>
        </details>
      </div>

      {/* '코드 메트릭' 패널 제거 — 고유 지표(소스파일/함수수 lizard/NLOC)는 '정적분석 › 코드 규모 (lizard)'로
          이동, 중복이던 '라인 커버리지' 카드는 위 Line Coverage와 겹쳐 삭제(사용자 요청 2026-07-03). */}

      {/* ── Complexity Table ── */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">함수 복잡도 상세</span>
          <button className="btn-sm" onClick={loadComplexity} disabled={complexityLoading}>
            {complexityLoading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          각 함수의 <b>순환복잡도</b>(Cyclomatic Complexity, 독립 실행 경로 수)입니다. 값이 클수록 분기가 많아 테스트·유지보수가 어렵습니다.{' '}
          임계값({threshold}) 초과는 빨강, 임계값의 70% 이상은 주황으로 표시합니다. <b>막대</b>는 복잡도 구간별 함수 수 분포,{' '}
          <b>산포도</b>는 복잡도(세로)×커버리지(가로)로 ‘복잡한데 덜 테스트된’ 위험 함수(좌상단)를 보여줍니다.
        </div>
        {rows.length > 0 ? (
          <>
            {compDist && (
              <div style={{ marginBottom: 10 }}>
                <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
                  <span className="text-sm" style={{ fontWeight: 600 }}>복잡도 분포</span>
                  <span className="text-sm text-muted">
                    함수 {compDist.total.toLocaleString()} · 최대 {compDist.max} · 평균 {compDist.avg.toFixed(1)} ·{' '}
                    <span style={{ color: compDist.over > 0 ? 'var(--color-danger)' : 'var(--color-success)', fontWeight: 600 }}>
                      임계(&gt;{threshold}) 초과 {compDist.over}
                    </span>
                  </span>
                </div>
                {/* 막대(좌)·산포도(우) 한 화면 — auto-fit으로 좁으면 세로 적층(인라인 grid가 미디어쿼리 덮어쓰는 문제 회피) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
                  <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6, display: 'flex', flexDirection: 'column' }}>
                    <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>구간별 함수 수 (막대)</div>
                    {/* 바 영역을 flex:1로 늘려 셀 높이(우측 산포도와 동일)를 가득 채운다. 막대는 트랙(flex:1)의 %로 스케일(최대 86% — 위 count 라벨 자리 확보). */}
                    <div style={{ flex: 1, minHeight: 160, display: 'flex', alignItems: 'stretch', gap: 6 }}>
                      {compDist.buckets.map((b, i) => {
                        const barPct = Math.max(b.count ? 4 : 0, Math.round((b.count / compDist.maxCount) * 86));
                        const col = `var(--color-${b.tone})`;
                        const pct = compDist.total ? Math.round((b.count / compDist.total) * 100) : 0;
                        return (
                          <div key={i} title={`${b.label}: ${b.count}개 (${pct}%)`}
                            style={{ flex: 1, height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                            <div style={{ flex: 1, minHeight: 0, width: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignItems: 'center' }}>
                              <div style={{ fontSize: 10, fontWeight: 700, color: b.count ? col : 'var(--text-muted)', marginBottom: 2 }}>{b.count}</div>
                              <div style={{ width: '100%', height: `${barPct}%`, background: col, opacity: b.count ? 1 : 0.18, borderRadius: '3px 3px 0 0' }} />
                            </div>
                            <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3, whiteSpace: 'nowrap' }}>{b.label}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
                    <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>복잡도 × 커버리지 (산포도)</div>
                    {scatterAvailable ? (
                      <ComplexityScatter points={compScatter.points} naCount={compScatter.naCount}
                        yMax={compScatter.yMax} threshold={threshold} />
                    ) : (
                      <div className="text-sm text-muted" style={{ padding: 8, lineHeight: 1.5 }}>
                        커버리지가 로드되면 표시됩니다 — 위쪽 ‘함수레벨 상세 불러오기’를 누르면
                        함수별 복잡도×커버리지가 산포도로 나타납니다.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <input type="text" placeholder="함수명/파일 검색..." value={compFilter} onChange={e => setCompFilter(e.target.value)}
                style={{ flex: 1, minWidth: 150, padding: '5px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }} />
              <select value={compSort} onChange={e => setCompSort(e.target.value)}
                style={{ padding: '5px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
                <option value="complexity">복잡도 높은 순</option>
                <option value="name">이름 순</option>
              </select>
              <span className="text-sm text-muted">{filteredRows.length}/{rows.length}건</span>
            </div>
            <div style={{ maxHeight: 350, overflowY: 'auto' }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                  <tr style={{ background: 'var(--bg)' }}><th>함수</th><th>파일</th><th>복잡도</th><th></th></tr>
                </thead>
                <tbody>
                  {filteredRows.slice(0, 100).map((r, i) => {
                    const cc = ccOf(r);
                    return (
                      <tr key={i} style={{ background: cc > threshold ? '#fee2e2' : cc > threshold * 0.7 ? '#fef9c3' : undefined }}>
                        <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{r.function ?? r.name ?? '-'}</td>
                        <td className="text-sm" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file ?? r.path ?? '-'}</td>
                        <td style={{ textAlign: 'center' }}>
                          <StatusBadge tone={cc > threshold ? 'danger' : cc > threshold * 0.7 ? 'warning' : 'success'}>{cc}</StatusBadge>
                        </td>
                        <td style={{ width: 60 }}>
                          <div style={{ height: 6, borderRadius: 3, background: '#e5e7eb' }}>
                            <div style={{ width: `${Math.min(cc / 30 * 100, 100)}%`, height: '100%', borderRadius: 3,
                              background: cc > threshold ? 'var(--color-danger)' : cc > threshold * 0.7 ? 'var(--color-warning)' : 'var(--color-success)' }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {filteredRows.length > 100 && <div className="text-muted text-sm" style={{ padding: 6, textAlign: 'center' }}>{filteredRows.length - 100}건 더 있음</div>}
          </>
        ) : complexity ? (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            이 빌드에 complexity.csv가 없습니다 — 복잡도 데이터가 동기화되지 않았습니다.
            {scmVcastPaths.length > 0
              ? ' 위 \'VectorCAST 테스트\' 패널의 \'SCM 경로에서 불러오기\'를 누르면 SCM VectorCAST 함수별 복잡도가 여기 표시됩니다.'
              : ' (PRQA HMR 복잡도는 위 정적분석 상세 패널을 참고하세요.)'}
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 12 }}>불러오기 버튼을 클릭하세요.</div>
        )}
      </div>

      {/* 정합성 검증 파일 경로 선택 (admin) — UT/IT 공용. onSelect는 openPicker가 target별로 주입. */}
      <PathPickerDialog
        open={!!picker}
        initialPath={picker?.current || ''}
        pattern={picker?.pattern || '*'}
        title={picker?.title || '경로 선택'}
        onSelect={picker?.onSelect}
        onClose={() => setPicker(null)}
      />
    </div>
  );
}
