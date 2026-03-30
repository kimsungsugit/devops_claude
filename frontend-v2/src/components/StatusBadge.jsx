export default function StatusBadge({ tone = 'neutral', children }) {
  return (
    <span className={`pill pill-${tone}`}>{children}</span>
  );
}
