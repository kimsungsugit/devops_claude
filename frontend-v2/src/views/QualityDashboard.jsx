import { useState, useEffect, useCallback, useRef } from 'react';
import { api, post } from '../api.js';
import { useToast } from '../App.jsx';

/* ── Doc type options ────────────────────────────────────────────── */
const DOC_TYPES = [
  { value: '', label: '전체' },
  { value: 'uds', label: 'UDS' },
  { value: 'sts', label: 'STS' },
  { value: 'suts', label: 'SUTS' },
  { value: 'sits', label: 'SITS' },
  { value: 'swut', label: 'SwUT' },
  { value: 'swit', label: 'SwIT' },
  { value: 'swsa', label: 'SwSA' },
  { value: 'swreport', label: '통합 Summary' },
];

/* ── Run shape accessors ─────────────────────────────────────────────
 * 백엔드 /api/quality/runs 는 점수/게이트를 run.summary.overall_score /
 * run.summary.gate_pass 로 (중첩) 내려준다. 과거 프론트는 run.total_score /
 * run.gate_passed (평탄) 를 가정해 항상 0점·FAIL 로 표시됐다.
 * flat 폴백(total_score/gate_passed)도 유지해 구 응답·테스트 픽스처와 호환. */
const runScore = (r) => r?.summary?.overall_score ?? r?.total_score ?? r?.score ?? 0;
const runGate = (r) => r?.summary?.gate_pass ?? r?.gate_passed ?? (runScore(r) >= 70);

/* ── SVG Bar Chart (no library) ──────────────────────────────────── */
function TrendChart({ data }) {
  if (!Array.isArray(data) || data.length === 0) {
    return (
      <div className="qd-empty">
        <span className="qd-empty-icon">--</span>
        <span>트렌드 데이터가 없습니다</span>
      </div>
    );
  }

  const width = 600;
  const height = 180;
  const padTop = 20;
  const padBottom = 28;
  const padLeft = 36;
  const padRight = 12;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const maxScore = 100;
  const barGap = 2;
  const barW = Math.max(4, Math.min(24, (chartW - barGap * data.length) / data.length));
  const totalBarArea = (barW + barGap) * data.length;
  const offsetX = padLeft + (chartW - totalBarArea) / 2;

  // Threshold line at 70
  const thresholdY = padTop + chartH * (1 - 70 / maxScore);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="qd-chart-svg"
      role="img"
      aria-label="품질 점수 트렌드 차트"
    >
      {/* Grid lines */}
      {[0, 25, 50, 75, 100].map(v => {
        const y = padTop + chartH * (1 - v / maxScore);
        return (
          <g key={v}>
            <line x1={padLeft} x2={width - padRight} y1={y} y2={y} className="qd-grid-line" />
            <text x={padLeft - 4} y={y + 3} className="qd-axis-label" textAnchor="end">{v}</text>
          </g>
        );
      })}

      {/* Threshold line */}
      <line
        x1={padLeft} x2={width - padRight}
        y1={thresholdY} y2={thresholdY}
        className="qd-threshold-line"
      />
      <text x={width - padRight + 2} y={thresholdY + 3} className="qd-threshold-label">70</text>

      {/* Bars */}
      {data.map((d, i) => {
        const score = d.overall_score ?? d.total_score ?? d.score ?? 0;
        // 막대 색은 백엔드 게이트 판정(gate_pass) 기준 — 점수>=70 추정과 분리해
        // 테이블 게이트 pill 과 시각 일관성 유지. gate_pass 없으면 70 폴백.
        const passed = d.gate_pass ?? (score >= 70);
        const barH = Math.max(1, (score / maxScore) * chartH);
        const x = offsetX + i * (barW + barGap);
        const y = padTop + chartH - barH;
        return (
          <g key={i}>
            <rect
              x={x} y={y}
              width={barW} height={barH}
              rx={2}
              className={passed ? 'qd-bar-pass' : 'qd-bar-fail'}
            >
              <title>{`#${d.run_id ?? i + 1}: ${score.toFixed(1)}점`}</title>
            </rect>
            {/* X-axis label (show every few) */}
            {(data.length <= 10 || i % Math.ceil(data.length / 10) === 0) && (
              <text
                x={x + barW / 2} y={height - 6}
                className="qd-axis-label"
                textAnchor="middle"
              >
                {d.run_id ?? i + 1}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ── Advice Panel ────────────────────────────────────────────────── */
function AdvicePanel({ runId, onClose }) {
  const toast = useToast();
  const [advice, setAdvice] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchAdvice = useCallback(async () => {
    setLoading(true);
    try {
      const data = await post(`/api/quality/runs/${runId}/advice`, {});
      setAdvice(data);
    } catch (err) {
      toast('error', `개선 제안 조회 실패: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [runId, toast]);

  useEffect(() => {
    fetchAdvice();
  }, [fetchAdvice]);

  if (loading) {
    return (
      <div className="panel qd-advice-panel">
        <div className="panel-header">
          <span className="panel-title">개선 제안 - Run #{runId}</span>
          <button className="btn-sm" onClick={onClose}>닫기</button>
        </div>
        <div className="qd-loading">분석 중...</div>
      </div>
    );
  }

  if (!advice) return null;

  // advisor/백엔드가 {error}(run 없음·모듈 없음 등)를 200으로 반환 — '제안 없음'(품질 양호)
  // 으로 위장하지 않도록 명시적 에러 패널로 분기.
  if (advice.error) {
    return (
      <div className="panel qd-advice-panel">
        <div className="panel-header">
          <span className="panel-title">개선 제안 - Run #{runId}</span>
          <button className="btn-sm" onClick={onClose}>닫기</button>
        </div>
        <div className="qd-empty">
          <span className="qd-empty-icon">!</span>
          <span>개선 제안을 불러올 수 없습니다: {advice.error}</span>
        </div>
      </div>
    );
  }

  // advisor.suggest_improvements 의 실제 키는 suggestions. 항목 필드는
  // priority / value / advice (구 프론트가 가정한 severity / current / suggestion 아님).
  const items = advice.suggestions || [];
  const SEVERITY_CLASS = {
    high: 'pill-danger',
    medium: 'pill-warning',
    low: 'pill-info',
  };
  const SEVERITY_LABEL = {
    high: '높음',
    medium: '보통',
    low: '낮음',
  };

  return (
    <div className="panel qd-advice-panel">
      <div className="panel-header">
        <span className="panel-title">개선 제안 - Run #{runId}</span>
        <button className="btn-sm" onClick={onClose}>닫기</button>
      </div>
      {/* 요약 줄 — 점수/게이트/제안수. unsupported(규칙 미정의)와 '품질 양호'를
          구분하는 단일 출처. 백엔드 summary 를 그대로 노출. */}
      {advice.summary && (
        <div className="qd-advice-summary">{advice.summary}</div>
      )}
      {items.length === 0 ? (
        // unsupported(규칙 미정의)는 위 summary 가 이미 안내 → 빈상태 텍스트 중복 생략.
        // supported 인데 제안 0 일 때만 '모든 항목 통과' 명시(품질 양호와 구분).
        advice.unsupported ? null : (
          <div className="qd-empty">
            <span>개선 제안이 없습니다 — 모든 항목이 임계값을 통과했습니다.</span>
          </div>
        )
      ) : (
        <div className="qd-advice-list">
          {items.map((item, i) => {
            const sev = item.priority ?? item.severity;
            const cur = item.value ?? item.current;
            const body = item.advice ?? item.suggestion;
            return (
              <div key={i} className="qd-advice-item">
                <div className="qd-advice-header">
                  <span className={`pill ${SEVERITY_CLASS[sev] || 'pill-neutral'}`}>
                    {SEVERITY_LABEL[sev] || sev}
                  </span>
                  <span className="qd-advice-metric">{item.label || item.metric || item.category}</span>
                  {cur != null && item.threshold != null && (
                    <span className="qd-advice-score">
                      {typeof cur === 'number' ? cur.toFixed(1) : cur}%
                      (임계값 {item.threshold}%)
                    </span>
                  )}
                </div>
                {body && (
                  <div className="qd-advice-body">{body}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Main: QualityDashboard ──────────────────────────────────────── */
export default function QualityDashboard() {
  const toast = useToast();

  const [docType, setDocType] = useState('');
  const [runs, setRuns] = useState([]);
  const [trend, setTrend] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [selectedRunId, setSelectedRunId] = useState(null);
  const loadSeq = useRef(0);

  /* Fetch runs + trend */
  const load = useCallback(async () => {
    const seq = ++loadSeq.current;  // docType 빠른 전환 시 out-of-order 응답 폐기용 토큰
    setLoading(true);
    setLoadError(null);
    try {
      // "전체"(docType='')는 doc_type 파라미터를 생략 → 백엔드의 미필터(전체) 분기.
      // 과거엔 `docType || 'uds'`로 강제해 "전체"가 사실상 uds만 조회했다.
      const dtParam = docType ? `&doc_type=${docType}` : '';
      const [runsData, trendData] = await Promise.all([
        api(`/api/quality/runs?limit=20${dtParam}`),
        api(`/api/quality/trend?last_n=20${dtParam}`),
      ]);
      if (seq !== loadSeq.current) return;  // 더 새 load가 시작됨 → stale 결과 무시
      // 백엔드 실제 응답 키: { runs: [...] } / { trend: [...] }.
      setRuns(runsData.runs || runsData.items || (Array.isArray(runsData) ? runsData : []));
      setTrend(trendData.trend || trendData.items || (Array.isArray(trendData) ? trendData : []));
    } catch (err) {
      if (seq !== loadSeq.current) return;
      setLoadError(err.message || '로드 실패');  // 장애를 '기록 없음'(빈 상태)과 구분
      toast('error', `품질 데이터 로드 실패: ${err.message}`);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [docType, toast]);

  useEffect(() => {
    load();
  }, [load]);

  /* Computed stats */
  const totalRuns = runs.length;
  const avgScore = totalRuns > 0
    ? runs.reduce((s, r) => s + runScore(r), 0) / totalRuns
    : 0;
  const passCount = runs.filter(r => runGate(r)).length;
  const passRate = totalRuns > 0 ? (passCount / totalRuns) * 100 : 0;

  return (
    <div className="qd-root">
      {/* Header */}
      <div className="qd-header">
        <h2 className="qd-title">Quality Dashboard</h2>
        <select
          className="qd-filter"
          value={docType}
          onChange={e => setDocType(e.target.value)}
        >
          {DOC_TYPES.map(dt => (
            <option key={dt.value} value={dt.value}>{dt.label}</option>
          ))}
        </select>
      </div>

      {/* KPI cards */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-label">총 실행수</div>
          <div className="stat-value">{totalRuns}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">평균 점수</div>
          <div className="stat-value">{avgScore.toFixed(1)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">게이트 통과율</div>
          <div className="stat-value">{passRate.toFixed(0)}%</div>
        </div>
      </div>

      {/* Trend chart */}
      <div className="panel qd-chart-panel">
        <div className="panel-header">
          <span className="panel-title">점수 트렌드</span>
          <button className="btn-sm" onClick={load} disabled={loading}>
            {loading ? '로딩...' : '새로고침'}
          </button>
        </div>
        <TrendChart data={trend} />
      </div>

      {/* Runs table */}
      <div className="panel qd-table-panel">
        <div className="panel-header">
          <span className="panel-title">최근 실행 목록</span>
        </div>
        {loadError ? (
          <div className="qd-empty">
            <span className="qd-empty-icon">!</span>
            <span>데이터 로드 실패: {loadError}</span>
            <button className="btn-sm" onClick={load} style={{ marginTop: 8 }}>재시도</button>
          </div>
        ) : runs.length === 0 ? (
          <div className="qd-empty">
            <span className="qd-empty-icon">--</span>
            <span>{loading ? '로딩 중...' : '실행 기록이 없습니다'}</span>
          </div>
        ) : (
          <div className="qd-table-wrap">
            <table className="qd-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>문서</th>
                  <th>점수</th>
                  <th>게이트</th>
                  <th>날짜</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(run => {
                  const score = runScore(run);
                  const passed = runGate(run);
                  const date = run.created_at || run.timestamp;
                  const dateStr = date
                    ? new Date(date).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' })
                    : '-';
                  return (
                    <tr key={run.id || run.run_id}>
                      <td>{run.id || run.run_id}</td>
                      <td>
                        <span className="pill pill-info">
                          {(run.doc_type || '-').toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <span className={passed ? 'qd-score-pass' : 'qd-score-fail'}>
                          {score.toFixed(1)}
                        </span>
                      </td>
                      <td>
                        <span className={`pill ${passed ? 'pill-success' : 'pill-danger'}`}>
                          {passed ? 'PASS' : 'FAIL'}
                        </span>
                      </td>
                      <td className="qd-date">{dateStr}</td>
                      <td>
                        <button
                          className="btn-sm"
                          onClick={() => setSelectedRunId(
                            selectedRunId === (run.id || run.run_id) ? null : (run.id || run.run_id)
                          )}
                        >
                          {selectedRunId === (run.id || run.run_id) ? '닫기' : 'Advice'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Advice panel */}
      {selectedRunId && (
        <AdvicePanel runId={selectedRunId} onClose={() => setSelectedRunId(null)} />
      )}
    </div>
  );
}
