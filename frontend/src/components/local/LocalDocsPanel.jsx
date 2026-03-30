const LocalDocsPanel = ({
  docsHtml,
  hasReportDir,
  generateLocalReports,
  loadLocalReports,
  localReportsLoading,
  localReportsError,
  localReports,
  downloadLocalReport,
}) => {
  return (
    <div>
      <h3>Docs</h3>
      {docsHtml ? (
        <iframe title="docs" srcDoc={docsHtml} className="doc-frame" />
      ) : (
        <div className="empty">문서 없음</div>
      )}
      <div className="panel">
        <h4>로컬 리포트 출력</h4>
        <div className="row">
          <button
            onClick={() => generateLocalReports && generateLocalReports()}
            disabled={!hasReportDir}
          >
            DOCX/XLSX 생성
          </button>
          <button
            onClick={loadLocalReports}
            disabled={!hasReportDir || localReportsLoading}
          >
            {localReportsLoading ? "로딩 중..." : "목록 갱신"}
          </button>
        </div>
        {localReportsError ? (
          <div className="error">{localReportsError}</div>
        ) : null}
        <div className="list">
          {(localReports || []).map((item) => (
            <div key={item.file || item.path} className="list-item">
              <span className="list-text">{item.file || "-"}</span>
              <span className="list-snippet">
                {item.size_mb ?? "-"} MB · {item.mtime || "-"}
              </span>
              <div className="row">
                <button
                  type="button"
                  className="btn-outline"
                  onClick={() =>
                    downloadLocalReport && downloadLocalReport(item.file)
                  }
                >
                  다운로드
                </button>
              </div>
            </div>
          ))}
          {(localReports || []).length === 0 && (
            <div className="empty">리포트 없음</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default LocalDocsPanel;
