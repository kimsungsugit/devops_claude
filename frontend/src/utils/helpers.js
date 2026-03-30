export const copyToClipboard = (text) => {
  try { navigator.clipboard.writeText(text); } catch {}
};

export const splitList = (value) =>
  value
    .split(/[,\n]/)
    .map((v) => v.trim())
    .filter(Boolean);

export const joinList = (value) => (Array.isArray(value) ? value.join(", ") : "");

export const jumpTo = (id) => {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
};

export function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function parseSearch(value) {
  const term = (value || "").trim();
  if (!term) return { mode: "none" };
  if (term.startsWith("/") && term.lastIndexOf("/") > 0) {
    const last = term.lastIndexOf("/");
    const pattern = term.slice(1, last);
    const flags = term.slice(last + 1) || "i";
    try {
      const regex = new RegExp(
        pattern,
        flags.includes("g") ? flags : `${flags}g`
      );
      return { mode: "regex", regex };
    } catch (e) {
      return { mode: "tokens", tokens: term.split(/\s+/).filter(Boolean) };
    }
  }
  const tokens = term.split(/\s+/).filter(Boolean);
  return { mode: tokens.length > 1 ? "tokens" : "single", tokens };
}

export function searchMatch(value, search) {
  if (search.mode === "none") return true;
  const hay = String(value || "").toLowerCase();
  if (search.mode === "regex") {
    search.regex.lastIndex = 0;
    return search.regex.test(value || "");
  }
  const tokens = search.tokens || [];
  return tokens.every((tok) => hay.includes(tok.toLowerCase()));
}

export const parseGitStatus = (text) => {
  const lines = String(text || "").split(/\r?\n/);
  const staged = [];
  const unstaged = [];
  const untracked = [];
  const byPath = {};
  let branchLine = "";
  const markPath = (path, type) => {
    if (!path) return;
    if (!byPath[path]) byPath[path] = type;
    if (byPath[path] === "modified" && type === "deleted") byPath[path] = "deleted";
    if (byPath[path] === "added" && type === "modified") byPath[path] = "modified";
  };
  for (const line of lines) {
    if (line.startsWith("##")) {
      branchLine = line.replace("##", "").trim();
      continue;
    }
    if (line.length < 3) continue;
    const x = line[0];
    const y = line[1];
    const path = line.slice(3).trim();
    if (x === "?" && y === "?") {
      untracked.push(path);
      markPath(path, "added");
      continue;
    }
    if (x !== " " && x !== "?") {
      staged.push(path);
      if (x === "D") markPath(path, "deleted");
      else if (x === "A") markPath(path, "added");
      else markPath(path, "modified");
    }
    if (y !== " ") {
      unstaged.push(path);
      if (y === "D") markPath(path, "deleted");
      else if (y === "A") markPath(path, "added");
      else if (y === "M") markPath(path, "modified");
    }
  }
  return { branchLine, staged, unstaged, untracked, byPath };
};

export const parseDiffRows = (text) => {
  const rows = [];
  const lines = String(text || "").split(/\r?\n/);
  let leftLine = null;
  let rightLine = null;
  let currentFile = "";
  for (const line of lines) {
    if (!line) {
      rows.push({ left: "", right: "", type: "empty", leftNo: null, rightNo: null, file: currentFile });
      continue;
    }
    if (line.startsWith("@@")) {
      const match = /@@\s+\-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@/.exec(line);
      if (match) {
        leftLine = Number(match[1]);
        rightLine = Number(match[3]);
      }
      rows.push({ left: line, right: line, type: "meta", leftNo: null, rightNo: null, file: currentFile });
      continue;
    }
    if (line.startsWith("+++ ")) {
      const file = line.replace("+++ ", "").trim();
      currentFile = file.startsWith("b/") ? file.slice(2) : file;
      rows.push({ left: line, right: line, type: "meta", leftNo: null, rightNo: null, file: currentFile });
      continue;
    }
    if (line.startsWith("--- ")) {
      const file = line.replace("--- ", "").trim();
      currentFile = file.startsWith("a/") ? file.slice(2) : file;
      rows.push({ left: line, right: line, type: "meta", leftNo: null, rightNo: null, file: currentFile });
      continue;
    }
    if (line.startsWith("diff ") || line.startsWith("index ")) {
      rows.push({ left: line, right: line, type: "meta", leftNo: null, rightNo: null, file: currentFile });
      continue;
    }
    if (line.startsWith("+")) {
      rows.push({ left: "", right: line.slice(1), type: "add", leftNo: null, rightNo: rightLine, file: currentFile });
      if (rightLine !== null) rightLine += 1;
      continue;
    }
    if (line.startsWith("-")) {
      rows.push({ left: line.slice(1), right: "", type: "del", leftNo: leftLine, rightNo: null, file: currentFile });
      if (leftLine !== null) leftLine += 1;
      continue;
    }
    if (line.startsWith(" ")) {
      rows.push({ left: line.slice(1), right: line.slice(1), type: "context", leftNo: leftLine, rightNo: rightLine, file: currentFile });
      if (leftLine !== null) leftLine += 1;
      if (rightLine !== null) rightLine += 1;
      continue;
    }
    rows.push({ left: line, right: line, type: "meta", leftNo: null, rightNo: null, file: currentFile });
  }
  return rows;
};

export const buildChatHistory = (messages) =>
  (messages || [])
    .filter(
      (msg) =>
        msg && msg.text && (msg.role === "user" || msg.role === "assistant")
    )
    .slice(-16)
    .map((msg) => ({ role: msg.role, text: msg.text }));

export const getInitialTheme = () => {
  if (typeof window === "undefined") return "light";
  return window.localStorage.getItem("devops_theme") || "light";
};
