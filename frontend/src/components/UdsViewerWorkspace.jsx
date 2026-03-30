import UdsResultViewer from "./UdsResultViewer";

const UdsViewerWorkspace = ({
  title = "UDS 상세 조회",
  files = [],
  selectedFilename = "",
  onSelectedFilenameChange,
  onRefreshFiles,
  onPickFile,
  filesLoading = false,
  filesError = "",
  onLoadView,
  viewData,
  viewLoading,
  viewError,
  urlStateKey,
  sourceRoot = "",
  onFetchCallGraph,
  onFetchDependencyMap,
  onFetchCodePreview,
  onRunImpactAnalyze,
  onGenerateTestData,
}) => {
  const rows = Array.isArray(files) ? files : [];

  return (
    <div className="panel uds-workspace">
      <h4>{title}</h4>
      <div className="row">
        {typeof onRefreshFiles === "function" || typeof onPickFile === "function" ? (
          <button
            type="button"
            className="btn-outline"
            onClick={typeof onPickFile === "function" ? onPickFile : onRefreshFiles}
            disabled={filesLoading}
          >
            {filesLoading ? "조회 중..." : typeof onPickFile === "function" ? "파일 선택" : "목록 새로고침"}
          </button>
        ) : null}
        <select
          value={selectedFilename}
          onChange={(e) =>
            typeof onSelectedFilenameChange === "function"
              ? onSelectedFilenameChange(e.target.value)
              : null
          }
        >
          <option value="">파일 선택</option>
          {rows.map((row) => {
            const name = String(row?.filename || row?.file || "").trim();
            if (!name) return null;
            return (
              <option key={name} value={name}>
                {name}
              </option>
            );
          })}
        </select>
        <button
          type="button"
          className="btn-outline"
          disabled={!selectedFilename}
          onClick={() =>
            typeof onLoadView === "function" && selectedFilename
              ? onLoadView(selectedFilename)
              : null
          }
        >
          상세 조회
        </button>
      </div>
      {filesError ? <div className="error">{filesError}</div> : null}
      <UdsResultViewer
        title={title}
        data={viewData}
        loading={viewLoading}
        error={viewError}
        serverMode
        urlStateKey={urlStateKey}
        sourceRoot={sourceRoot}
        onFetchCallGraph={onFetchCallGraph}
        onFetchDependencyMap={onFetchDependencyMap}
        onFetchCodePreview={onFetchCodePreview}
        onRunImpactAnalyze={onRunImpactAnalyze}
        onGenerateTestData={onGenerateTestData}
        onRefresh={() =>
          typeof onLoadView === "function" && selectedFilename
            ? onLoadView(selectedFilename)
            : null
        }
        onRequestData={(params) =>
          typeof onLoadView === "function" && selectedFilename
            ? onLoadView(selectedFilename, params)
            : null
        }
      />
    </div>
  );
};

export default UdsViewerWorkspace;
