import { useEffect, useMemo, useState } from 'react'
import { createAppointment, listAppointments, listTeams } from '../lib/api.js'
import {
  MONTHS,
  WEEKDAYS,
  addMonths,
  isSameDay,
  isSameMonth,
  monthGrid,
  startOfDay,
  toKey,
} from '../lib/date.js'

// The bookable day, in 30-minute slots.
const DAY_START = 8
const DAY_END = 18
const SLOT_MINUTES = 30
const DURATIONS = [15, 30, 45, 60, 90]

const SLOTS = (() => {
  const out = []
  for (let minutes = DAY_START * 60; minutes < DAY_END * 60; minutes += SLOT_MINUTES) {
    out.push(
      `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(
        minutes % 60,
      ).padStart(2, '0')}`,
    )
  }
  return out
})()

const minutesOf = (time) => {
  const [h, m] = time.split(':').map(Number)
  return h * 60 + m
}

const timeOf = (value) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : `${String(date.getHours()).padStart(2, '0')}:${String(
        date.getMinutes(),
      ).padStart(2, '0')}`
}

/** Local ISO (no Z): the API stores naive local times, so a UTC instant here
 *  would book the wrong hour. */
const isoLocal = (date, time = '00:00') => {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${time}:00`
}

const addMinutesTo = (time, minutes) => {
  const total = minutesOf(time) + minutes
  return `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(
    total % 60,
  ).padStart(2, '0')}`
}

/**
 * Book an appointment against a case: pick the day on a calendar, the team,
 * and a free slot. Slots already taken by that team are shown as blocked, so
 * a clash is visible before booking rather than after.
 */
function BookAppointmentDialog({ caseId, patientName, onClose, onBooked }) {
  const today = startOfDay(new Date())
  const [month, setMonth] = useState(() => new Date())
  const [date, setDate] = useState(today)
  const [teams, setTeams] = useState([])
  const [teamId, setTeamId] = useState('')
  const [slot, setSlot] = useState('')
  const [duration, setDuration] = useState(30)
  const [booked, setBooked] = useState([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    listTeams()
      .then((data) => {
        if (cancelled) return
        setTeams(data.teams)
        setTeamId((prev) => prev || data.teams[0]?.consultant_team_id || '')
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // What that team already has booked on the chosen day.
  const dayKey = toKey(date)
  useEffect(() => {
    if (!teamId) return undefined
    let cancelled = false
    listAppointments({
      consultantTeamId: teamId,
      from: isoLocal(date, '00:00'),
      to: isoLocal(date, '23:59'),
    })
      .then((data) => {
        if (!cancelled) setBooked(data.appointments)
      })
      .catch(() => {
        if (!cancelled) setBooked([])
      })
    return () => {
      cancelled = true
    }
    // dayKey rather than the Date object, which is a new reference each render.
  }, [teamId, dayKey]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Slot -> the appointment occupying it, if any. */
  const takenBy = useMemo(() => {
    const map = new Map()
    for (const item of booked) {
      if (item.status === 'cancelled') continue
      const start = minutesOf(timeOf(item.start_time))
      const end = minutesOf(timeOf(item.end_time) || timeOf(item.start_time))
      for (const time of SLOTS) {
        const at = minutesOf(time)
        if (at >= start && at < Math.max(end, start + 1)) map.set(time, item)
      }
    }
    return map
  }, [booked])

  /** A slot is unusable if it, or anything the duration runs into, is taken. */
  const blocked = (time) => {
    const end = minutesOf(time) + duration
    if (end > DAY_END * 60) return true
    return SLOTS.some(
      (candidate) =>
        minutesOf(candidate) >= minutesOf(time) &&
        minutesOf(candidate) < end &&
        takenBy.has(candidate),
    )
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!teamId) return setError('Choose a consultant team.')
    if (!slot) return setError('Choose a time slot.')

    setError('')
    setSaving(true)
    try {
      await createAppointment({
        case_id: caseId,
        consultant_team_id: teamId,
        start_time: isoLocal(date, slot),
        end_time: isoLocal(date, addMinutesTo(slot, duration)),
        appointment_type: 'consultation',
        status: 'scheduled',
      })
      onBooked()
    } catch (exc) {
      setError(exc.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal modal-wide" onSubmit={submit}>
        <div className="panel-head">
          <div>
            <h2>Book appointment</h2>
            <p>{patientName}</p>
          </div>
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <div className="book-grid">
          <div>
            <div className="book-cal-bar">
              <button
                type="button"
                className="icon-btn"
                aria-label="Previous month"
                onClick={() => setMonth((prev) => addMonths(prev, -1))}
              >
                ‹
              </button>
              <span className="picker-year">
                {MONTHS[month.getMonth()]} {month.getFullYear()}
              </span>
              <button
                type="button"
                className="icon-btn"
                aria-label="Next month"
                onClick={() => setMonth((prev) => addMonths(prev, 1))}
              >
                ›
              </button>
            </div>

            <div className="day-grid-pick">
              {WEEKDAYS.map((day) => (
                <span key={day} className="day-head">
                  {day.slice(0, 1)}
                </span>
              ))}
              {monthGrid(month).map((day) => (
                <button
                  key={day.toDateString()}
                  type="button"
                  className={`pick-day${isSameMonth(day, month) ? '' : ' is-muted'}${
                    isSameDay(day, date) ? ' is-active' : ''
                  }${isSameDay(day, today) ? ' is-today' : ''}`}
                  onClick={() => {
                    setDate(startOfDay(day))
                    setSlot('')
                  }}
                >
                  {day.getDate()}
                </button>
              ))}
            </div>

            <div className="edit-field book-field">
              <label className="field-label" htmlFor="book-team">
                Consultant team
              </label>
              <select
                id="book-team"
                className="input"
                value={teamId}
                onChange={(event) => {
                  setTeamId(event.target.value)
                  setSlot('')
                  setBooked([])
                }}
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

            <div className="edit-field book-field">
              <label className="field-label" htmlFor="book-duration">
                Duration
              </label>
              <select
                id="book-duration"
                className="input"
                value={duration}
                onChange={(event) => {
                  setDuration(Number(event.target.value))
                  setSlot('')
                }}
              >
                {DURATIONS.map((minutes) => (
                  <option key={minutes} value={minutes}>
                    {minutes} minutes
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <h3 className="detail-title">
              Slots · {String(date.getDate()).padStart(2, '0')}{' '}
              {MONTHS[date.getMonth()]}
            </h3>
            {!teamId ? (
              <p className="field-hint">Select a team to see its availability.</p>
            ) : (
              <div className="slot-grid">
                {SLOTS.map((time) => {
                  const isBlocked = blocked(time)
                  const holder = takenBy.get(time)
                  return (
                    <button
                      key={time}
                      type="button"
                      className={`slot${isBlocked ? ' is-blocked' : ''}${
                        slot === time ? ' is-active' : ''
                      }`}
                      disabled={isBlocked}
                      title={
                        holder
                          ? `Booked: ${holder.patient_name || 'appointment'}`
                          : undefined
                      }
                      onClick={() => setSlot(time)}
                    >
                      {time}
                    </button>
                  )
                })}
              </div>
            )}
            <p className="field-hint slot-legend">
              Greyed slots are already booked for this team.
            </p>
          </div>
        </div>

        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={saving || !slot || !teamId}
          >
            {slot
              ? `Book ${slot}–${addMinutesTo(slot, duration)}`
              : 'Book appointment'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default BookAppointmentDialog
