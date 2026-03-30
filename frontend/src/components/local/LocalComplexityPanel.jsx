const LocalComplexityPanel = ({
  loadComplexity,
  topComplexity,
  onOpenEditorFile,
  complexityRows,
}) => {
  return (
    <div>
      <h3>Complexity</h3>
      <div className="row">
        <button onClick={loadComplexity}>복잡도 로드</button>
        <span className="hint">표시 {topComplexity.length}건</span>
      </div>
      <div className="list">
        {topComplexity.map((row) => (
          <button
            key={`${row.file}-${row.func}-${row.ccn}`}
            className="list-item"
            type="button"
            onClick={() =>
              onOpenEditorFile && onOpenEditorFile(row.file, row.line)
            }
          >
            <span className="list-text">{row.func}</span>
            <span className="list-snippet">
              {row.file} · CCN {row.ccn} · NLOC {row.nloc} · L
              {row.line || "-"}
            </span>
          </button>
        ))}
        {topComplexity.length === 0 && (
          <div className="empty">복잡도 데이터 없음</div>
        )}
      </div>
      <details className="detail-raw">
        <summary>원본 JSON 보기</summary>
        <pre className="json">
          {JSON.stringify(complexityRows, null, 2)}
        </pre>
      </details>
    </div>
  );
};

export default LocalComplexityPanel;
