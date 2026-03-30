const JenkinsScmPanel = ({
  scmPresets,
  scmDisplay,
  jenkinsScmUrl,
  setJenkinsScmUrl,
  jenkinsScmType,
  setJenkinsScmType,
  jenkinsScmUsername,
  setJenkinsScmUsername,
  jenkinsScmPassword,
  setJenkinsScmPassword,
  jenkinsScmBranch,
  setJenkinsScmBranch,
  jenkinsScmRevision,
  setJenkinsScmRevision,
  loadJenkinsScmInfo,
  downloadJenkinsSourceRoot,
}) => {
  return (
    <div>
      <h3>Jenkins SCM</h3>
      <div className="form-grid-2 compact">
        <label>SCM 서버 프리셋</label>
        <select
          value={jenkinsScmUrl || ""}
          onChange={(e) => {
            const next = scmPresets.find((p) => p.url === e.target.value);
            if (!next) return;
            setJenkinsScmType(next.type || "svn");
            setJenkinsScmUrl(next.url);
            setJenkinsScmUsername(next.username || "");
            if (!next.url) {
              setJenkinsScmBranch("");
              setJenkinsScmRevision("");
            }
          }}
        >
          {scmPresets.map((preset) => (
            <option key={preset.label} value={preset.url}>
              {preset.label}
            </option>
          ))}
        </select>
        <label>SCM 종류</label>
        <select
          value={jenkinsScmType || "svn"}
          onChange={(e) => setJenkinsScmType(e.target.value)}
        >
          <option value="svn">SVN</option>
          <option value="git">Git</option>
        </select>
        <label>SCM URL</label>
        <input
          value={jenkinsScmUrl || ""}
          onChange={(e) => setJenkinsScmUrl(e.target.value)}
          placeholder="http://ip/svn/project"
        />
        <label>아이디</label>
        <input
          value={jenkinsScmUsername || ""}
          onChange={(e) => setJenkinsScmUsername(e.target.value)}
        />
        <label>비밀번호</label>
        <input
          type="password"
          value={jenkinsScmPassword || ""}
          onChange={(e) => setJenkinsScmPassword(e.target.value)}
        />
        <label>브랜치</label>
        <input
          value={jenkinsScmBranch || ""}
          onChange={(e) => setJenkinsScmBranch(e.target.value)}
          placeholder="(Git 전용)"
        />
        <label>리비전</label>
        <div className="row">
          <input
            value={jenkinsScmRevision || ""}
            onChange={(e) => setJenkinsScmRevision(e.target.value)}
            placeholder="(SVN 전용, 비우면 HEAD)"
          />
          <button
            type="button"
            className="btn-outline"
            onClick={loadJenkinsScmInfo}
            disabled={!jenkinsScmUrl || (jenkinsScmType || "svn") !== "svn"}
          >
            HEAD 조회
          </button>
        </div>
      </div>
      <div className="hint">
        SCM 정보는 자동 저장됩니다. 소스 다운로드 시 우선 사용됩니다.
      </div>
      <div className="row">
        <button
          type="button"
          className="btn-outline"
          onClick={() =>
            downloadJenkinsSourceRoot && downloadJenkinsSourceRoot("")
          }
          disabled={!jenkinsScmUrl || !downloadJenkinsSourceRoot}
        >
          소스 다운로드
        </button>
      </div>
      <pre className="json">{JSON.stringify(scmDisplay, null, 2)}</pre>
    </div>
  );
};

export default JenkinsScmPanel;
