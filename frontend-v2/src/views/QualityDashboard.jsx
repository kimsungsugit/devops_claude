import { useState, useEffect, useCallback } from 'react';
import { api, post } from '../api.js';
import { useToast } from '../App.jsx';

/* ── Doc type options ────────────────────────────────────────────── */
const DOC_TYPES = [
  { value: '', label: '전체' },
  { value: 'sts', label: 'STS' },
  { value: 'suts', label: 'SUTS' },
  { value: 'uds', label: 'UDS' },
];

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
        const score = d.total_score ?? d.score ?? 0;
        const passed = score >= 70;
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

  const items = advice.items || advice.suggestions || [];
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
      {items.length === 0 ? (
        <div className="qd-empty">
          <span>개선 제안이 없습니다</span>
        </div>
      ) : (
        <div className="qd-advice-list">
          {items.map((item, i) => (
            <div key={i} className="qd-advice-item">
              <div className="qd-advice-header">
                <span className={`pill ${SEVERITY_CLASS[item.severity] || 'pill-neutral'}`}>
                  {SEVERITY_LABEL[item.severity] || item.severity}
                </span>
                <span className="qd-advice-metric">{item.metric || item.category}</span>
                {item.current != null && item.threshold != null && (
                  <span className="qd-advice-score">
                    {typeof item.current === 'number' ? item.current.toFixed(1) : item.current}%
                    (임계값 {item.threshold}%)
                  </span>
                )}
              </div>
              {item.suggestion && (
                <div className="qd-advice-body">{item.suggestion}</div>
              )}
            </div>
          ))}
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
  const [selectedRunId, setSelectedRunId] = useState(null);

  /* Fetch runs + trend */
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const dt = docType || 'uds';
      const qs = `?limit=20&doc_type=${dt}`;
      const trendQs = `?doc_type=${dt}&last_n=20`;
      const [runsData, trendData] = await Promise.all([
        api(`/api/quality/runs${qs}`),
        api(`/api/quality/trend${trendQs}`),
      ]);
      setRuns(runsData.items || runsData.runs || runsData || []);
      setTrend(trendData.items || trendData.points || trendData || []);
    } catch (err) {
      toast('error', `품질 데이터 로드 실패: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [docType, toast]);

  useEffect(() => {
    load();
  }, [load]);

  /* Computed stats */
  const totalRuns = runs.length;
  const avgScore = totalRuns > 0
    ? runs.reduce((s, r) => s + (r.total_score ?? r.score ?? 0), 0) / totalRuns
    : 0;
  const passCount = runs.filter(r => r.gate_passed ?? (r.total_score ?? r.score ?? 0) >= 70).length;
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
        {runs.length === 0 ? (
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
                  const score = run.total_score ?? run.score ?? 0;
                  const passed = run.gate_passed ?? score >= 70;
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
                        <span className={score >= 70 ? 'qd-score-pass' : 'qd-score-fail'}>
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
