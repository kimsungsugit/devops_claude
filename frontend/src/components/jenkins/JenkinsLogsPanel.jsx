const JenkinsLogsPanel = ({
  loadJenkinsLogs,
  jenkinsJobUrl,
  jenkinsLogPath,
  setJenkinsLogPath,
  readJenkinsLog,
  jenkinsLogs,
  jenkinsLogContent,
}) => {
  return (
    <div>
      <h3>Jenkins Logs</h3>
      <div className="row">
        <button onClick={loadJenkinsLogs} disabled={!jenkinsJobUrl}>
          로그 목록
        </button>
        <input
          placeholder="상대 경로"
          value={jenkinsLogPath}
          onChange={(e) => setJenkinsLogPath(e.target.value)}
        />
        <button
          onClick={() => readJenkinsLog(jenkinsLogPath)}
          disabled={!jenkinsLogPath}
        >
          읽기
        </button>
      </div>
      <pre className="json">{JSON.stringify(jenkinsLogs, null, 2)}</pre>
      <pre className="json">{jenkinsLogContent}</pre>
    </div>
  );
};

export default JenkinsLogsPanel;
