import { memo } from 'react';

// `title` 은 hover 설명(툴팁). 없던 시절엔 넘겨도 **조용히 버려져서**, 배지에 사유를
// 달아 뒀다고 생각한 자리가 실제로는 아무 설명도 없었다.
export default memo(function StatusBadge({ tone = 'neutral', title, children }) {
  return <span className={`pill pill-${tone}`} title={title}>{children}</span>;
});
