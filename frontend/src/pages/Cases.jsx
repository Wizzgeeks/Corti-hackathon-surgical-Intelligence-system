import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { initials } from '../data/cases.js'
import { listCases } from '../lib/api.js'

const PAGE_SIZE = 20

/** Flag counts, most serious first.
 *
 *  Low flags are deliberately not shown: on a caseload table they are noise,
 *  and a row with nothing on it reads as "nothing to worry about" — which is
 *  what a low flag means. Critical is shown with high, in red, because a
 *  critical flag is the one thing that must never be hidden here. */
function FlagCounts({ counts }) {
  const shown = [
    { key: 'critical', label: 'Critical', tone: 'high' },
    { key: 'high', label: 'High', tone: 'high' },
    { key: 'medium', label: 'Medium', tone: 'medium' },
  ].filter((entry) => (counts?.[entry.key] ?? 0) > 0)

  if (shown.length === 0) return <span className="cell-sub">—</span>

  return (
    <span className="flag-counts">
      {shown.map((entry) => (
        <span key={entry.key} className={`sev sev-${entry.tone}`}>
          {entry.label} {counts[entry.key]}
        </span>
      ))}
    </span>
  )
}

function Cases() {
  const navigate = useNavigate()
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    // Only the list endpoint runs here; the detail page fetches its own case.
    let cancelled = false
    listCases({ limit: PAGE_SIZE, skip: 0 })
      .then((data) => {
        if (!cancelled) setResult(data)
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <section className="panel">
        <h2>Cases</h2>
        <p className="form-error" role="alert">
          {error}
        </p>
      </section>
    )
  }

  // The full-screen loader covers the fetch; render nothing underneath it.
  if (!result) return null

  const { cases, total } = result

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>All cases</h2>
        <span className="count">
          {cases.length === total
            ? `${total} cases`
            : `${cases.length} of ${total} cases`}
        </span>
      </div>

      {cases.length === 0 ? (
        <p>No cases yet. Upload a referral to create the first one.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Patient name</th>
                <th scope="col">Gender</th>
                <th scope="col">Age</th>
                <th scope="col">Urgency</th>
                <th scope="col">Flags</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((row) => (
                <tr
                  key={row.case_id}
                  className="row-link"
                  tabIndex={0}
                  onClick={() => navigate(`/cases/${row.case_id}`)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      navigate(`/cases/${row.case_id}`)
                    }
                  }}
                >
                  <td>
                    <div className="cell-user">
                      <span className="avatar avatar-soft">
                        {initials(row.patient_name)}
                      </span>
                      <span>
                        <span className="cell-strong">
                          {row.patient_name || '—'}
                        </span>
                        <br />
                        <span className="cell-sub">{row.status || '—'}</span>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className="tag">{row.patient_gender || '—'}</span>
                  </td>
                  <td className="num">{row.patient_age || '—'}</td>
                  <td>
                    {row.is_urgent ? (
                      <span className="sev sev-high">Urgent</span>
                    ) : (
                      <span className="cell-sub">Routine</span>
                    )}
                  </td>
                  <td>
                    <FlagCounts counts={row.flag_counts} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default Cases
