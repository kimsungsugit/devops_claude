export const classNames = (...items) => items.filter(Boolean).join(' ');

export const normalizePct = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return num <= 1 ? num * 100 : num;
};

export const formatPct = (value) => {
  const pct = normalizePct(value);
  if (pct == null) return "-";
  return `${pct.toFixed(1)}%`;
};

export const toneForStatus = (state) => {
  const raw = String(state || "").toLowerCase();
  if (raw.includes("fail") || raw.includes("error")) return "failed";
  if (raw.includes("run")) return "running";
  if (raw.includes("success") || raw.includes("complete")) return "success";
  return "info";
};
