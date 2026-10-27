export const PAGE_SIZE = 25;

export function Pager({ offset, total, onChange, size = PAGE_SIZE }: { offset: number; total: number; onChange: (o: number) => void; size?: number }) {
  if (total <= size) return total > 0 ? <div className="pager"><span>{total} {total === 1 ? "record" : "records"}</span></div> : null;
  const end = Math.min(offset + size, total);
  return (
    <nav className="pager" aria-label="Pagination">
      <span>{offset + 1}–{end} of {total}</span>
      <div className="row">
        <button className="btn small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>Previous</button>
        <button className="btn small" disabled={end >= total} onClick={() => onChange(offset + size)}>Next</button>
      </div>
    </nav>
  );
}
