import { useState } from "react";

const JenkinsRagIngestPanel = ({ runRagIngestFiles }) => {
  const [ragIngestFiles, setRagIngestFiles] = useState([]);
  const [ragIngestCategory, setRagIngestCategory] = useState("requirements");
  const [ragIngestTags, setRagIngestTags] = useState("");
  const [ragChunkSize, setRagChunkSize] = useState(1200);
  const [ragChunkOverlap, setRagChunkOverlap] = useState(200);
  const [ragMaxChunks, setRagMaxChunks] = useState(12);
  const [ragLastResult, setRagLastResult] = useState(null);

  return (
    <div className="panel-group">
      <div className="panel">
        <h3>RAG 인제스트</h3>
        <div className="section">
          <label>문서 파일 업로드</label>
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
            onChange={(e) =>
              setRagIngestFiles(Array.from(e.target.files || []))
            }
          />
          {ragIngestFiles.length > 0 ? (
            <div className="hint">
              선택됨: {ragIngestFiles.map((f) => f.name).join(", ")}
            </div>
          ) : (
            <div className="hint">문서를 선택해주세요.</div>
          )}
        </div>
        <div className="section">
          <label>카테고리</label>
          <select
            value={ragIngestCategory}
            onChange={(e) => setRagIngestCategory(e.target.value)}
          >
            <option value="requirements">requirements</option>
            <option value="uds">uds</option>
            <option value="code">code</option>
            <option value="general">general</option>
          </select>
          <label>태그 (쉼표 구분)</label>
          <input
            value={ragIngestTags}
            onChange={(e) => setRagIngestTags(e.target.value)}
            placeholder="예) req, srs, sds"
          />
        </div>
        <div className="section">
          <label>Chunk size</label>
          <input
            type="number"
            min={200}
            max={4000}
            value={ragChunkSize}
            onChange={(e) =>
              setRagChunkSize(Number(e.target.value || 1200))
            }
          />
          <label>Chunk overlap</label>
          <input
            type="number"
            min={0}
            max={2000}
            value={ragChunkOverlap}
            onChange={(e) =>
              setRagChunkOverlap(Number(e.target.value || 200))
            }
          />
          <label>Max chunks per file</label>
          <input
            type="number"
            min={1}
            max={50}
            value={ragMaxChunks}
            onChange={(e) => setRagMaxChunks(Number(e.target.value || 12))}
          />
        </div>
        <div className="row">
          <button
            type="button"
            onClick={async () => {
              if (!runRagIngestFiles) return;
              const res = await runRagIngestFiles(
                ragIngestFiles,
                ragIngestCategory,
                ragIngestTags,
                {
                  chunk_size: ragChunkSize,
                  chunk_overlap: ragChunkOverlap,
                  max_chunks: ragMaxChunks,
                }
              );
              setRagLastResult(res || null);
            }}
          >
            RAG 인제스트 실행
          </button>
        </div>
        <div className="hint">
          UDS 생성 시 AI 옵션을 켜면, 인제스트된 문서와 소스코드를 함께
          참고합니다.
        </div>
        {ragLastResult ? (
          <div className="panel">
            <h4>최근 인제스트 결과</h4>
            <pre className="json">
              {JSON.stringify(ragLastResult, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default JenkinsRagIngestPanel;
