import { useEffect, useState } from 'react'
import { listTeams } from '../lib/api.js'

/** Local datetime <-> the `datetime-local` input's value. Built from local
 *  parts rather than toISOString(), which would shift the time by the UTC
 *  offset and book the wrong slot. */
const toLocalInput = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const plusMinutes = (value, minutes) => {
  const date = new Date(value)
  date.setMinutes(date.getMinutes() + minutes)
  return toLocalInput(date)
}

/** Book or edit one appointment. `appointment` is null for a new booking. */
function AppointmentForm({
  appointment,
  defaultDate,
  cases,
  onClose,
  onDelete,
  onSubmit,
}) {
  const [teams, setTeams] = useState([])
  const [error, setError] = useState('')
  const [form, setForm] = useState(() => {
    const start = appointment?.start_time
      ? toLocalInput(appointment.start_time)
      : toLocalInput(defaultDate ?? new Date())
    return {
      start_time: start,
      end_time: appointment?.end_time
        ? toLocalInput(appointment.end_time)
        : plusMinutes(start, 30),
      consultant_team_id: appointment?.consultant_team_id ?? '',
      case_id: appointment?.case_id ?? '',
      appointment_type: appointment?.appointment_type || 'consultation',
      status: appointment?.status || 'scheduled',
    }
  })

  useEffect(() => {
    let cancelled = false
    listTeams()
      .then((data) => {
        if (!cancelled) setTeams(data.teams)
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const submit = async (event) => {
    event.preventDefault()
    if (new Date(form.end_time) <= new Date(form.start_time)) {
      setError('The end time must be after the start time.')
      return
    }
    setError('')
    try {
      await onSubmit(form)
    } catch (exc) {
      setError(exc.message)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <div className="panel-head">
          <h2>{appointment ? 'Edit appointment' : 'New appointment'}</h2>
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <div className="edit-list">
          <div className="field-row">
            <div className="edit-field">
              <label className="field-label" htmlFor="appt-start">
                Start
              </label>
              <input
                id="appt-start"
                type="datetime-local"
                className="input"
                required
                value={form.start_time}
                onChange={(e) => {
                  set('start_time', e.target.value)
                  // Keep a sane 30-minute slot as the start moves.
                  if (!appointment) set('end_time', plusMinutes(e.target.value, 30))
                }}
              />
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="appt-end">
                End
              </label>
              <input
                id="appt-end"
                type="datetime-local"
                className="input"
                required
                value={form.end_time}
                onChange={(e) => set('end_time', e.target.value)}
              />
            </div>
          </div>

          <div className="edit-field">
            <label className="field-label" htmlFor="appt-team">
              Consultant team
            </label>
            <select
              id="appt-team"
              className="input"
              required
              value={form.consultant_team_id}
              onChange={(e) => set('consultant_team_id', e.target.value)}
            >
              <option value="">Select a team</option>
              {teams.map((team) => (
                <option
                  key={team.consultant_team_id}
                  value={team.consultant_team_id}
                >
                  {team.name}
                  {team.speciality ? ` — ${team.speciality}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="edit-field">
            <label className="field-label" htmlFor="appt-case">
              Case
            </label>
            <select
              id="appt-case"
              className="input"
              value={form.case_id}
              disabled={Boolean(appointment)}
              onChange={(e) => set('case_id', e.target.value)}
            >
              <option value="">Select a case</option>
              {cases.map((row) => (
                <option key={row.case_id} value={row.case_id}>
                  {row.patient_name}
                </option>
              ))}
            </select>
          </div>

          <div className="field-row">
            <div className="edit-field">
              <label className="field-label" htmlFor="appt-type">
                Type
              </label>
              <select
                id="appt-type"
                className="input"
                value={form.appointment_type}
                onChange={(e) => set('appointment_type', e.target.value)}
              >
                <option value="consultation">Consultation</option>
                <option value="surgery">Surgery</option>
              </select>
            </div>
            <div className="edit-field">
              <label className="field-label" htmlFor="appt-status">
                Status
              </label>
              <select
                id="appt-status"
                className="input"
                value={form.status}
                onChange={(e) => set('status', e.target.value)}
              >
                <option value="scheduled">Scheduled</option>
                <option value="completed">Completed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
          </div>
        </div>

        <div className="form-actions">
          {onDelete && (
            <button
              type="button"
              className="btn btn-danger form-actions-left"
              onClick={onDelete}
            >
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary">
            {appointment ? 'Save appointment' : 'Book appointment'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default AppointmentForm
