const RiskScorePanel = ({ riskBreakdown, riskScore }) => (
  <details className="risk-breakdown-panel">
    <summary className="summary-chart" style={{ cursor: "pointer" }}>
      <div className="summary-title">리스크 점수 (클릭하여 상세 보기)</div>
      <div className="bar-row">
        <span className="bar-label">Risk</span>
        <div className="bar">
          <div
            className="bar-fill bar-fill-risk"
            style={{ width: `${riskScore}%` }}
          />
        </div>
        <span className="bar-value">{riskScore.toFixed(0)}</span>
      </div>
    </summary>
    <div className="risk-detail">
      {riskBreakdown.items.length > 0 ? (
        <>
          <div className="risk-stack-bar">
            {riskBreakdown.items.map((item, idx) => (
              <div
                key={idx}
                className={`risk-stack-segment risk-seg-${idx % 5}`}
                style={{ flex: item.penalty }}
                title={`${item.label}: -${item.penalty}점`}
              />
            ))}
          </div>
          <div className="risk-items-list">
            {riskBreakdown.items.map((item, idx) => (
              <div key={idx} className="risk-item-row">
                <span className={`risk-dot risk-seg-${idx % 5}`} />
                <span className="risk-item-label">{item.label}</span>
                <span className="risk-item-penalty">-{item.penalty}점</span>
                {item.count != null && item.count > 0 && <span className="hint">({item.count}건)</span>}
              </div>
            ))}
            <div className="risk-item-row risk-item-total">
              <span>총 페널티</span>
              <span className="risk-item-penalty">-{riskBreakdown.totalPenalty}점</span>
            </div>
          </div>
          {riskBreakdown.items[0] && (
            <div className="risk-cta">
              💡 "{riskBreakdown.items[0].label}"을(를) 먼저 해결하면 +{riskBreakdown.items[0].penalty}점 개선됩니다
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <div className="empty-state-msg">페널티 없음</div>
          <div className="empty-state-hint">모든 항목이 양호합니다</div>
        </div>
      )}
    </div>
  </details>
);

export default RiskScorePanel;
