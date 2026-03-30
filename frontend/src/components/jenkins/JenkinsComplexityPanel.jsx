const JenkinsComplexityPanel = ({
  loadJenkinsComplexity,
  jenkinsJobUrl,
  jenkinsComplexityRows,
}) => {
  return (
    <div>
      <h3>Jenkins Complexity</h3>
      <div className="row">
        <button onClick={loadJenkinsComplexity} disabled={!jenkinsJobUrl}>
          불러오기
        </button>
      </div>
      <pre className="json">
        {JSON.stringify(jenkinsComplexityRows, null, 2)}
      </pre>
    </div>
  );
};

export default JenkinsComplexityPanel;
