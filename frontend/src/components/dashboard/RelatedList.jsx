const RelatedList = ({ items, emptyLabel = "—", formatter }) => {
  if (!items || items.length === 0)
    return <div className="empty">{emptyLabel}</div>;
  return (
    <ul className="plain-list">
      {items.slice(0, 6).map((item, idx) => (
        <li key={`${String(item)}-${idx}`}>
          {formatter ? formatter(item) : String(item)}
        </li>
      ))}
    </ul>
  );
};

export default RelatedList;
