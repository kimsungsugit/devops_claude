const renderInline = (text) => {
  const parts = [];
  const src = String(text || "");
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(src)) !== null) {
    if (match.index > lastIndex) {
      parts.push(src.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={`${match.index}-b`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      parts.push(<code key={`${match.index}-c`}>{token.slice(1, -1)}</code>);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < src.length) {
    parts.push(src.slice(lastIndex));
  }
  return parts;
};

export function renderMarkdownLite(text) {
  const lines = String(text || "").split(/\r?\n/);
  const blocks = [];
  let listItems = [];
  let paragraph = [];
  let tableRows = [];
  let codeLines = [];
  let inFence = false;

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: "list", items: listItems });
      listItems = [];
    }
  };
  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushTable = () => {
    if (tableRows.length > 0) {
      blocks.push({ type: "table", rows: tableRows });
      tableRows = [];
    }
  };
  const flushCode = () => {
    if (codeLines.length > 0) {
      blocks.push({ type: "code", text: codeLines.join("\n") });
      codeLines = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (inFence) {
        flushCode();
        inFence = false;
      } else {
        flushTable();
        flushList();
        flushParagraph();
        inFence = true;
      }
      continue;
    }
    if (inFence) {
      codeLines.push(rawLine);
      continue;
    }
    if (!line.trim()) {
      flushTable();
      flushList();
      flushParagraph();
      continue;
    }
    if (line.startsWith("### ")) {
      flushTable();
      flushList();
      flushParagraph();
      blocks.push({ type: "heading", level: 3, text: line.slice(4).trim() });
      continue;
    }
    if (line.startsWith("## ")) {
      flushTable();
      flushList();
      flushParagraph();
      blocks.push({ type: "heading", level: 2, text: line.slice(3).trim() });
      continue;
    }
    if (line.startsWith("# ")) {
      flushTable();
      flushList();
      flushParagraph();
      blocks.push({ type: "heading", level: 1, text: line.slice(2).trim() });
      continue;
    }
    if (line.startsWith("- ")) {
      flushTable();
      flushParagraph();
      listItems.push(line.slice(2).trim());
      continue;
    }
    if (line.startsWith("|")) {
      flushList();
      flushParagraph();
      const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
      const isDivider = cells.every((cell) => /^:?-{3,}:?$/.test(cell));
      if (!isDivider && cells.length > 0) {
        tableRows.push(cells);
      }
      continue;
    }
    flushTable();
    paragraph.push(line.trim());
  }
  flushCode();
  flushTable();
  flushList();
  flushParagraph();

  return blocks.map((block, idx) => {
    if (block.type === "heading") {
      const Tag = block.level === 1 ? "h5" : "h6";
      return <Tag key={idx} className="report-heading">{renderInline(block.text)}</Tag>;
    }
    if (block.type === "list") {
      return (
        <ul key={idx} className="report-list">
          {block.items.map((item, itemIdx) => <li key={itemIdx}>{renderInline(item)}</li>)}
        </ul>
      );
    }
    if (block.type === "code") {
      return <pre key={idx} className="report-code">{block.text}</pre>;
    }
    if (block.type === "table") {
      const [header = [], ...rows] = block.rows;
      return (
        <div key={idx} className="report-table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                {header.map((cell, cellIdx) => <th key={cellIdx}>{renderInline(cell)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr key={rowIdx}>
                  {row.map((cell, cellIdx) => <td key={cellIdx}>{renderInline(cell)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <p key={idx} className="report-paragraph">{renderInline(block.text)}</p>;
  });
}

export default function ReportMarkdownPreview({ text, className = "", style = {} }) {
  return (
    <div className={`report-preview ${className}`.trim()} style={style}>
      {renderMarkdownLite(text)}
    </div>
  );
}
