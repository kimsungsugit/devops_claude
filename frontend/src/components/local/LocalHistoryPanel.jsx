import { useMemo } from "react";

const LocalHistoryPanel = ({
  historyRows,
  history,
  statusTone,
  formatValue,
  formatHistoryTests,
  formatHistoryCoverage,
}) => {
  const { recent10, covTrend, hasCovData, maxCov } = useMemo(() => {
    const r10 = historyRows.slice(0, 10).reverse();
    const trend = r10.map((e, i) => {
      const cov = e?.coverage?.line_rate_pct ?? e?.coverage?.line_rate ?? e?.coverageLine ?? null;
      return { idx: i, value: cov != null ? Number(cov) : null, label: (e?.generated_at || e?.timestamp || "").slice(5, 16) };
    });
    const hasData = trend.some((d) => d.value != null);
    const max = Math.max(...trend.filter((d) => d.value != null).map((d) => d.value), 100);
    return { recent10: r10, covTrend: trend, hasCovData: hasData, maxCov: max };
  }, [historyRows]);

  return (
    <div>
      <h3>History</h3>
      {hasCovData && (
        <div className="history-trend">
          <h4>커버리지 추이 (최근 {recent10.length}건)</h4>
          <div className="trend-chart">
            {covTrend.map((d) => (
              <div key={d.idx} className="trend-bar-col">
                <div className="trend-bar-wrap">
                  {d.value != null && (
                    <div className="trend-bar-fill" style={{ height: `${(d.value / maxCov) * 100}%` }}>
                      <span className="trend-bar-val">{d.value.toFixed(0)}%</span>
                    </div>
                  )}
                </div>
                <span className="trend-bar-label">{d.label || "-"}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="list">
        {historyRows.map((entry, idx) => {
          const entryKey = entry?.generated_at || entry?.timestamp || `hist-${idx}`;
          return (
            <details key={entryKey} className="history-entry">
              <summary className="list-item">
                <span className={`status-chip tone-${statusTone(entry?.state || entry?.status || entry?.phase)}`}>
                  {formatValue(entry?.state || entry?.status || entry?.phase || "-")}
                </span>
                <span className="list-snippet">{formatValue(entry?.generated_at || entry?.timestamp || entry?.time || entry?.created_at)}</span>
                <span className="list-snippet">{formatHistoryTests(entry)}</span>
                <span className="list-snippet">커버리지 {formatHistoryCoverage(entry)}</span>
              </summary>
              <div className="history-detail">
                <div className="detail-grid">
                  {entry?.build?.ok != null && <><span className="detail-label">빌드</span><span className={`detail-value tone-${entry.build.ok ? "success" : "failed"}`}>{entry.build.ok ? "성공" : "실패"}</span></>}
                  {entry?.tests?.ok != null && <><span className="detail-label">테스트</span><span className={`detail-value tone-${entry.tests.ok ? "success" : "failed"}`}>{entry.tests.ok ? "성공" : "실패"}</span></>}
                  {entry?.agent?.iterations != null && <><span className="detail-label">에이전트</span><span className="detail-value">{entry.agent.iterations}회 · {entry.agent.stop_reason || "-"}</span></>}
                </div>
              </div>
            </details>
          );
        })}
        {historyRows.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <div className="empty-state-msg">실행 이력이 없습니다</div>
            <div className="empty-state-hint">워크플로우를 실행하면 이력이 여기에 기록됩니다</div>
          </div>
        )}
      </div>
      <details className="detail-raw">
        <summary>원본 JSON 보기</summary>
        <pre className="json">{JSON.stringify(history, null, 2)}</pre>
      </details>
    </div>
  );
};

export default LocalHistoryPanel;
