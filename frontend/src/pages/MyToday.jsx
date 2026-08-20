import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SpokenBriefing from '../components/SpokenBriefing.jsx'
import { getTodaySummary, listTeams } from '../lib/api.js'
import { toKey } from '../lib/date.js'

/** How each consultation is described in the list. */
const TYPE_WORDS = {
  new: 'New consultation',
  follow_up: 'Follow-up',
  post_surgery: 'Post-surgery',
}

/** One number and what it counts. */
function Stat({ label, value, tone }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ''}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

/**
 * The consultant's day at a glance.
 *
 * The breakdown of consultations is derived server-side from what else each
 * case has booked — a case with an earlier operation is post-surgery, one
 * with an earlier clinic visit is a follow-up — so the page asks one
 * question and displays the answer.
 */
function MyToday() {
  const navigate = useNavigate()
  const [teams, setTeams] = useState([])
  const [teamId, setTeamId] = useState('')
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')

  const today = toKey(new Date())

  useEffect(() => {
    let cancelled = false
    listTeams()
      .then((data) => {
        if (cancelled) return
        setTeams(data.teams)
        // Pick the first team so the page has something to show on arrival.
        setTeamId((prev) => prev || (data.teams[0]?.consultant_team_id ?? ''))
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const [rewriting, setRewriting] = useState(false)

  const load = useCallback(
    (options) => {
    if (!teamId) return undefined
    return getTodaySummary(teamId, today, options)
      .then((data) => {
        setError('')
        setSummary(data)
      })
      .catch((exc) => setError(exc.message))
    },
    [teamId, today],
  )

  /** Ask Corti to write it again — for when the case notes changed but the
   *  list of appointments did not, which the stored briefing cannot see. */
  const rewrite = async () => {
    setRewriting(true)
    try {
      await load({ refresh: true })
    } finally {
      setRewriting(false)
    }
  }

  useEffect(() => {
    load()
  }, [load])

  const selected = teams.find((team) => team.consultant_team_id === teamId)

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>My today</h2>
          <p className="cell-sub">
            {new Date().toLocaleDateString(undefined, {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
            {selected?.speciality ? ` · ${selected.speciality}` : ''}
          </p>
        </div>
        <label className="today-picker">
          <span className="field-label">Consultant</span>
          <select
            className="input"
            value={teamId}
            onChange={(event) => setTeamId(event.target.value)}
          >
            {teams.length === 0 && <option value="">No consultants yet</option>}
            {teams.map((team) => (
              <option
                key={team.consultant_team_id}
                value={team.consultant_team_id}
              >
                {team.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {!summary ? (
        teams.length === 0 && !error ? (
          <p>Add a consultant team before this page has anything to show.</p>
        ) : null
      ) : (
        <>
          <div className="stat-row">
            <Stat label="Cases today" value={summary.cases} />
            <Stat label="Consultations" value={summary.consultations} />
            <Stat label="Surgeries" value={summary.surgeries} />
            <Stat
              label="Cases with high flags"
              value={summary.high_flag_cases}
              tone={summary.high_flag_cases > 0 ? 'alert' : undefined}
            />
          </div>

          <h3 className="detail-title today-sub">Of those consultations</h3>
          <div className="stat-row">
            <Stat label="New" value={summary.new_consultations} />
            <Stat label="Follow-up" value={summary.follow_up_consultations} />
            <Stat
              label="Post-surgery"
              value={summary.post_surgery_consultations}
            />
          </div>

          {/* The same day as prose. Read aloud on the way in, or scanned
              here — the list below repeats it in a form you can click. */}
          <section className="briefing">
            <div className="panel-head">
              <div>
                <h3 className="detail-title">Today, out loud</h3>
                {!summary.briefing_by_corti && summary.cases > 0 && (
                  <p className="cell-sub">
                    Written from the booking list — Corti was not reachable
                    when this was generated.
                  </p>
                )}
              </div>
              <button
                type="button"
                className="btn btn-sm"
                disabled={rewriting}
                onClick={rewrite}
              >
                {rewriting ? 'Rewriting…' : 'Rewrite'}
              </button>
            </div>
            <SpokenBriefing key={summary.summary_text} text={summary.summary_text} />
          </section>

          {summary.appointments.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Patient</th>
                    <th scope="col">Type</th>
                    <th scope="col">Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.appointments.map((item) => (
                    <tr
                      key={item.appointment_id}
                      className={item.case_id ? 'row-link' : undefined}
                      tabIndex={item.case_id ? 0 : undefined}
                      onClick={() =>
                        item.case_id && navigate(`/cases/${item.case_id}`)
                      }
                      onKeyDown={(event) => {
                        if (!item.case_id) return
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          navigate(`/cases/${item.case_id}`)
                        }
                      }}
                    >
                      <td className="cell-strong">{item.time}</td>
                      <td>
                        {item.patient_name}
                        <br />
                        <span className="cell-sub">
                          {[item.patient_age, item.patient_gender]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </td>
                      <td>{TYPE_WORDS[item.category] ?? item.appointment_type}</td>
                      <td>
                        {item.has_high_flag ? (
                          <span className="sev sev-high">High</span>
                        ) : (
                          <span className="cell-sub">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {summary.cases === 0 && (
            <p className="today-empty">Nothing booked for this consultant today.</p>
          )}
        </>
      )}
    </section>
  )
}

export default MyToday
