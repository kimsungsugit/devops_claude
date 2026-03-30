import { useEffect, useRef, useState } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-c";
import "prismjs/components/prism-clike";

const CodeHighlight = ({ code = "", language = "c", maxHeight = 520 }) => {
  const codeRef = useRef(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (codeRef.current) {
      Prism.highlightElement(codeRef.current);
    }
  }, [code, language]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard not available */
    }
  };

  const lines = (code || "").split("\n");

  if (!code || !code.trim()) {
    return <div className="hint">코드 데이터가 없습니다.</div>;
  }

  return (
    <div className="code-hl-wrap">
      <div className="code-hl-toolbar">
        <span className="code-hl-lang">{(language || "text").toUpperCase()}</span>
        <span className="code-hl-lines">{lines.length} lines</span>
        <button type="button" className="btn-outline btn-xs" onClick={handleCopy}>
          {copied ? "복사됨!" : "복사"}
        </button>
      </div>
      <div className="code-hl-body" style={{ maxHeight }}>
        <div className="code-hl-gutter" aria-hidden="true">
          {lines.map((_, i) => (
            <span key={i}>{i + 1}</span>
          ))}
        </div>
        <pre className="code-hl-pre">
          <code ref={codeRef} className={`language-${language}`}>
            {code}
          </code>
        </pre>
      </div>
    </div>
  );
};

export default CodeHighlight;
