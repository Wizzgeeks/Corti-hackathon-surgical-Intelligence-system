/**
 * Corti's coded diagnoses for the case, read from its consultation summaries.
 *
 * Purely presentational: the case page owns the fetch, because it is the one
 * that knows when the agent run has settled and the summaries are final.
 *
 * Loads inside its own panel rather than behind the full-screen loader — the
 * rest of the case is readable while the coding is still being worked out,
 * and blocking it would be a poor trade for a supporting detail.
 */
function MedicalCoding({ codes, loading, error, note, onRetry }) {
  return (
    <section className="coding" aria-busy={loading || undefined}>
      <div className="coding-head">
        <div>
          <h3 className="detail-title">Medical coding</h3>
          <p className="cell-sub">
            Coded by Corti from the consultation summaries.
          </p>
        </div>
        {!loading && onRetry && (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            Recode
          </button>
        )}
      </div>

      {loading ? (
        /* Skeleton rather than a spinner: the panel keeps its height, so
           the rest of the case does not jump when the codes land. */
        <ul className="coding-list" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <li key={index} className="coding-chip coding-chip-skeleton">
              <span className="coding-code" />
              <span className="coding-desc" />
            </li>
          ))}
        </ul>
      ) : error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : codes.length > 0 ? (
        <ul className="coding-list">
          {codes.map((item, index) => (
            <li key={`${item.code}-${index}`} className="coding-chip">
              <span className="coding-code">{item.code || '—'}</span>
              <span className="coding-desc">
                {item.description || 'No description given.'}
                {item.evidence && (
                  <span className="coding-evidence">{item.evidence}</span>
                )}
              </span>
              {typeof item.confidence === 'number' && (
                <span className="coding-confidence">
                  {Math.round(item.confidence * 100)}%
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="coding-empty">
          {note || 'No codes returned for this case yet.'}
        </p>
      )}
    </section>
  )
}

export default MedicalCoding
