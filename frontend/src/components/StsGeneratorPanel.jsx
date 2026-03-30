import { useCallback, useState } from "react";
import ExcelArtifactViewer from "./ExcelArtifactViewer";

export default function StsGeneratorPanel({
  pickDirectory,
  pickFile,
  isJenkins,
  sourceRoot,
  onSourceRootChange,
  srsPath,
  onSrsPathChange,
  sdsPath = "",
  onSdsPathChange,
  hsisPath = "",
  onHsisPathChange,
  udsPath = "",
  onUdsPathChange,
  stpPath = "",
  onStpPathChange,
  templatePath,
  onTemplatePathChange,
  projectId,
  onProjectIdChange,
  version,
  onVersionChange,
  asilLevel,
  onAsilLevelChange,
  maxTc,
  onMaxTcChange,
  loading,
  notice,
  progressPct,
  progressMsg,
  files,
  filesLoading,
  viewData,
  previewData,
  previewLoading,
  previewSheet,
  onPreviewSheetChange,
  onGenerate,
  onRefreshFiles,
  onOpenFile,
  onLoadPreview,
}) {
  const [selectedFilename, setSelectedFilename] = useState("");
  const [showAdvancedOverrides, setShowAdvancedOverrides] = useState(false);

  const handlePickDir = useCallback(async (setter, label) => {
    if (!pickDirectory) return;
    const result = await pickDirectory(label || "Select directory");
    if (result?.path) setter(result.path);
  }, [pickDirectory]);

  const handlePickFile = useCallback(async (setter, label) => {
    if (typeof pickFile === "function") {
      const picked = await pickFile(label || "Select file");
      if (picked) setter(String(picked));
      return;
    }
    await handlePickDir(setter, label);
  }, [handlePickDir, pickFile]);

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>STS Generator</h3>
          <div className="row" style={{ gap: 8, alignItems: "center" }}>
            <span className="hint">{isJenkins ? "Jenkins" : "Local"}</span>
            <button
              type="button"
              className="btn-outline"
              onClick={() => setShowAdvancedOverrides((value) => !value)}
            >
              {showAdvancedOverrides ? "Hide Advanced" : "Advanced Overrides"}
            </button>
          </div>
        </div>
        <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
          {showAdvancedOverrides ? (
            <div className="card" style={{ display: "grid", gap: 10 }}>
              <div className="hint">
                기본값은 Analyzer Global Context를 사용합니다. 다른 테스트나 이전 문서 세트를 써야 할 때만 override를 엽니다.
              </div>
              <div>
                <label>Source Root</label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={sourceRoot} onChange={(e) => onSourceRootChange(e.target.value)} placeholder="Source root" />
                  <button type="button" className="btn-outline" onClick={() => handlePickDir(onSourceRootChange, "Select source root")}>Browse</button>
                </div>
              </div>
              <div>
                <label>SRS Path <span className="hint" style={{ fontSize: "0.8em" }}>(필수)</span></label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={srsPath} onChange={(e) => onSrsPathChange(e.target.value)} placeholder="SRS docx path" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onSrsPathChange, "Select STS SRS document")}>Browse</button>
                </div>
              </div>
              <div>
                <label>SDS Path <span className="hint" style={{ fontSize: "0.8em" }}>(선택, 설계 컨텍스트)</span></label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={sdsPath} onChange={(e) => typeof onSdsPathChange === "function" && onSdsPathChange(e.target.value)} placeholder="SDS docx path (optional)" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onSdsPathChange, "Select SDS document")}>Browse</button>
                </div>
              </div>
              <div>
                <label>HSIS Path <span className="hint" style={{ fontSize: "0.8em" }}>(선택, HW/SW 인터페이스)</span></label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={hsisPath} onChange={(e) => typeof onHsisPathChange === "function" && onHsisPathChange(e.target.value)} placeholder="HSIS xlsx path (optional, auto-discovered)" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onHsisPathChange, "Select HSIS document")}>Browse</button>
                </div>
              </div>
              <div>
                <label>UDS Path <span className="hint" style={{ fontSize: "0.8em" }}>(선택, 함수 설명 참고)</span></label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={udsPath} onChange={(e) => typeof onUdsPathChange === "function" && onUdsPathChange(e.target.value)} placeholder="UDS docx/xlsm path (optional)" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onUdsPathChange, "Select UDS document")}>Browse</button>
                </div>
              </div>
              <div>
                <label>STP Path <span className="hint" style={{ fontSize: "0.8em" }}>(선택, 시험 계획)</span></label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={stpPath} onChange={(e) => typeof onStpPathChange === "function" && onStpPathChange(e.target.value)} placeholder="STP docx path (optional)" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onStpPathChange, "Select STP document")}>Browse</button>
                </div>
              </div>
              <div>
                <label>Template Path</label>
                <div className="row" style={{ gap: 6 }}>
                  <input value={templatePath} onChange={(e) => onTemplatePathChange(e.target.value)} placeholder="Optional template path" />
                  <button type="button" className="btn-outline" onClick={() => handlePickFile(onTemplatePathChange, "Select STS template")}>Browse</button>
                </div>
              </div>
            </div>
          ) : (
            <div className="hint">
              기본은 Analyzer Global Context를 사용합니다. 예외적인 문서 세트가 필요할 때만 Advanced Overrides를 여세요.
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
            <input value={projectId} onChange={(e) => onProjectIdChange(e.target.value)} placeholder="Project ID" />
            <input value={version} onChange={(e) => onVersionChange(e.target.value)} placeholder="Version" />
            <select value={asilLevel} onChange={(e) => onAsilLevelChange(e.target.value)}>
              <option value="">N/A</option>
              <option value="QM">QM</option>
              <option value="ASIL-A">ASIL-A</option>
              <option value="ASIL-B">ASIL-B</option>
              <option value="ASIL-C">ASIL-C</option>
              <option value="ASIL-D">ASIL-D</option>
            </select>
            <input type="number" min={1} max={20} value={maxTc} onChange={(e) => onMaxTcChange(parseInt(e.target.value, 10) || 5)} placeholder="Max TC/Req" />
          </div>
          {notice ? <div className="hint">{notice}</div> : null}
          {loading ? <div className="hint">{progressMsg || "Running..."} {progressPct ? `(${progressPct}%)` : ""}</div> : null}
          <div className="row">
            <button type="button" onClick={onGenerate} disabled={loading}>Generate STS</button>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="row">
          <button type="button" className="btn-outline" onClick={onRefreshFiles} disabled={filesLoading}>
            {filesLoading ? "로딩 중..." : "목록 새로고침"}
          </button>
          <select value={selectedFilename} onChange={(e) => setSelectedFilename(e.target.value)} style={{ flex: 1 }}>
            <option value="">파일 선택</option>
            {(Array.isArray(files) ? files : []).map((row) => {
              const name = String(row?.filename || "").trim();
              if (!name) return null;
              return <option key={name} value={name}>{name}</option>;
            })}
          </select>
          <button
            type="button"
            className="btn-outline"
            disabled={!selectedFilename}
            onClick={() => {
              if (selectedFilename) {
                onOpenFile(selectedFilename);
                onLoadPreview(selectedFilename);
              }
            }}
          >
            상세 조회
          </button>
        </div>
      </div>

      <ExcelArtifactViewer
        artifactType="sts"
        title="STS Result Viewer"
        viewData={viewData}
        previewData={previewData}
        previewLoading={previewLoading}
        previewSheet={previewSheet}
        onPreviewSheetChange={onPreviewSheetChange}
        onLoadPreview={onLoadPreview}
        files={files}
        filesLoading={filesLoading}
        onRefreshFiles={onRefreshFiles}
        onOpenFile={onOpenFile}
      />
    </div>
  );
}
