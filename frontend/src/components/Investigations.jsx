import { useCallback, useEffect, useState } from 'react'
import AddInvestigationDialog from './AddInvestigationDialog.jsx'
import { listInvestigations } from '../lib/api.js'

/** Enough of the summary to tell reports apart in the table. */
const preview = (text, limit = 140) => {
  const value = (text ?? '').replace(/\s+/g, ' ').trim()
  if (!value) return ''
  return value.length > limit ? `${value.slice(0, limit).trimEnd()}…` : value
}

/**
 * Investigation reports on a case.
 *
 * Each row is a stored PDF plus the brief Corti extracted from it. The
 * summary is grouped prose that runs well past a table cell, so the cell
 * shows the opening of it and the whole thing opens in a dialog.
 */
function Investigations({ caseId }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  // The report whose full summary is open, if any.
  const [viewing, setViewing] = useState(null)

  const load = useCallback(() => {
    // The case record loads after this mounts, so the first render has no id
    // yet — asking for `undefined` is a guaranteed 400.
    if (!caseId) return Promise.resolve()

    return listInvestigations(caseId)
      .then((data) => {
        setError('')
        setItems(data)
      })
      .catch((exc) => setError(exc.message))
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Investigations</h2>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setAdding(true)}
        >
          Add report
        </button>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {items?.length === 0 ? (
        <p>No investigation reports uploaded yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Reported at</th>
                <th scope="col">Summary</th>
              </tr>
            </thead>
            <tbody>
              {(items ?? []).map((item) => (
                <tr key={item.investigation_id}>
                  <td className="cell-strong">{item.name || '—'}</td>
                  <td>{item.reported_at_text || '—'}</td>
                  <td className="cell-wrap">
                    {item.summary ? (
                      <>
                        {preview(item.summary)}{' '}
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => setViewing(item)}
                        >
                          View full summary
                        </button>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {adding && (
        <AddInvestigationDialog
          caseId={caseId}
          onClose={() => setAdding(false)}
          onAdded={async () => {
            setAdding(false)
            // Refetched rather than appended: the stored record carries the
            // server's reported_at and summary.
            await load()
          }}
        />
      )}

      {viewing && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal">
            <div className="panel-head">
              <div>
                <h2>{viewing.name}</h2>
                <p className="cell-sub">
                  Reported {viewing.reported_at_text || '—'}
                </p>
              </div>
            </div>
            <pre className="summary-text summary-facts">{viewing.summary}</pre>
            <div className="form-actions">
              <button
                type="button"
                className="btn"
                onClick={() => setViewing(null)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

export default Investigations
