import { useCallback, useEffect, useMemo, useState } from 'react'
import AppointmentForm from '../components/AppointmentForm.jsx'
import PeriodPicker from '../components/PeriodPicker.jsx'
import {
  createAppointment,
  deleteAppointment,
  listAppointments,
  listCases,
  updateAppointment,
} from '../lib/api.js'
import {
  MONTHS,
  toKey,
  WEEKDAYS,
  addDays,
  addMonths,
  endOfWeek,
  formatLong,
  formatShort,
  isSameDay,
  isSameMonth,
  monthGrid,
  startOfWeek,
} from '../lib/date.js'

const VIEWS = [
  { id: 'month', label: 'Month' },
  { id: 'week', label: 'Week' },
  { id: 'day', label: 'Day' },
]

const TONE = { consultation: 'accent', surgery: 'gold' }

const timeOf = (value) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

const Block = ({ item, onOpen }) => (
  <button
    type="button"
    className={`block block-${
      item.status === 'cancelled' ? 'muted' : TONE[item.appointment_type] ?? 'good'
    }`}
    onClick={(event) => {
      // The month/week cell behind this opens the day view.
      event.stopPropagation()
      onOpen?.(item)
    }}
  >
    <span className="block-time">{timeOf(item.start_time)}</span>
    <span className="block-name">{item.patient_name || 'Unassigned'}</span>
    <span className="block-kind">{item.consultant_name || item.appointment_type}</span>
  </button>
)

function MonthView({ cursor, today, byDay, onPickDay, onOpen }) {
  return (
    <div className="cal-month">
      {WEEKDAYS.map((day) => (
        <div key={day} className="cal-head">
          {day}
        </div>
      ))}
      {monthGrid(cursor).map((date) => {
        const items = byDay.get(toKey(date)) ?? []
        return (
          <button
            key={date.toDateString()}
            type="button"
            className={`cal-cell${isSameMonth(date, cursor) ? '' : ' is-muted'}${
              isSameDay(date, today) ? ' is-today' : ''
            }`}
            onClick={() => onPickDay(date)}
          >
            <span className="cal-date">{date.getDate()}</span>
            <span className="cal-blocks">
              {items.slice(0, 3).map((item) => (
                <Block key={item.appointment_id} item={item} onOpen={onOpen} />
              ))}
              {items.length > 3 && (
                <span className="cal-more">+{items.length - 3} more</span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function WeekView({ cursor, today, byDay, onPickDay, onOpen }) {
  const start = startOfWeek(cursor)
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i))

  return (
    <div className="cal-week">
      {days.map((date) => {
        const items = byDay.get(toKey(date)) ?? []
        return (
          <div
            key={date.toDateString()}
            className={`week-col${isSameDay(date, today) ? ' is-today' : ''}`}
          >
            <button
              type="button"
              className="week-col-head"
              onClick={() => onPickDay(date)}
            >
              <span className="cal-head">{WEEKDAYS[(date.getDay() + 6) % 7]}</span>
              <span className="week-col-date">{date.getDate()}</span>
            </button>
            <div className="week-col-body">
              {items.length === 0 ? (
                <span className="cal-empty">—</span>
              ) : (
                items.map((item) => <Block key={item.appointment_id} item={item} onOpen={onOpen} />)
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DayView({ cursor, byDay, onOpen }) {
  const items = byDay.get(toKey(cursor)) ?? []
  const hours = Array.from({ length: 11 }, (_, i) => i + 8) // 08:00–18:00

  return (
    <div className="cal-day">
      {hours.map((hour) => {
        const slot = `${String(hour).padStart(2, '0')}:`
        const inHour = items.filter((item) =>
          timeOf(item.start_time).startsWith(slot),
        )
        return (
          <div key={hour} className="day-row">
            <span className="day-hour">{`${String(hour).padStart(2, '0')}:00`}</span>
            <div className="day-slot">
              {inHour.map((item) => (
                <Block key={item.appointment_id} item={item} onOpen={onOpen} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** Local ISO string (no Z) — the API stores naive local times, so sending a
 *  UTC instant here would shift every query by the timezone offset. */
const isoLocal = (date) => {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}:00`
}

/** The date span the current view needs, padded to whole weeks for the month
 *  grid so its leading/trailing days are populated too. */
const windowFor = (view, cursor) => {
  if (view === 'day') return [startOfDay(cursor), endOfDay(cursor)]
  if (view === 'week')
    return [startOfDay(startOfWeek(cursor)), endOfDay(endOfWeek(cursor))]
  const grid = monthGrid(cursor)
  return [startOfDay(grid[0]), endOfDay(grid[grid.length - 1])]
}

const startOfDay = (date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0)
const endOfDay = (date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59)

function Appointments() {
  const [view, setView] = useState('day')
  const [cursor, setCursor] = useState(() => new Date())
  const [appointments, setAppointments] = useState([])
  const [cases, setCases] = useState([])
  const [error, setError] = useState('')
  // null = closed, 'new' = booking, otherwise the appointment being edited.
  const [editing, setEditing] = useState(null)
  const today = new Date()

  const [from, to] = windowFor(view, cursor)
  const fromKey = isoLocal(from)
  const toKeyIso = isoLocal(to)

  const load = useCallback(
    () =>
      listAppointments({ from: fromKey, to: toKeyIso })
        .then((data) => {
          setError('')
          setAppointments(data.appointments)
        })
        .catch((exc) => setError(exc.message)),
    [fromKey, toKeyIso],
  )

  useEffect(() => {
    load()
  }, [load])

  // The booking form needs cases to attach to; fetched once.
  useEffect(() => {
    let cancelled = false
    listCases({ limit: 200 })
      .then((data) => {
        if (!cancelled) setCases(data.cases)
      })
      .catch(() => {
        // A failed case list only limits the dropdown; the calendar still works.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const byDay = useMemo(() => {
    const map = new Map()
    for (const item of appointments) {
      if (!item.start_time) continue
      const key = toKey(new Date(item.start_time))
      const list = map.get(key)
      if (list) list.push(item)
      else map.set(key, [item])
    }
    for (const list of map.values())
      list.sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))
    return map
  }, [appointments])

  const save = async (form) => {
    const payload = {
      ...form,
      start_time: `${form.start_time}:00`,
      end_time: `${form.end_time}:00`,
    }
    if (editing === 'new') {
      await createAppointment(payload)
    } else {
      await updateAppointment(editing.appointment_id, {
        start_time: payload.start_time,
        end_time: payload.end_time,
        consultant_team_id: payload.consultant_team_id,
        appointment_type: payload.appointment_type,
        status: payload.status,
      })
    }
    setEditing(null)
    await load()
  }

  const remove = async () => {
    if (!window.confirm('Delete this appointment?')) return
    try {
      await deleteAppointment(editing.appointment_id, editing.case_id)
      setEditing(null)
      await load()
    } catch (exc) {
      setError(exc.message)
    }
  }

  const step = (direction) => {
    if (view === 'month') setCursor((prev) => addMonths(prev, direction))
    else if (view === 'week') setCursor((prev) => addDays(prev, direction * 7))
    else setCursor((prev) => addDays(prev, direction))
  }

  const title =
    view === 'month'
      ? `${MONTHS[cursor.getMonth()]} ${cursor.getFullYear()}`
      : view === 'week'
        ? `${formatShort(startOfWeek(cursor))} – ${formatShort(
            endOfWeek(cursor),
          )} ${endOfWeek(cursor).getFullYear()}`
        : formatLong(cursor)

  const openDay = (date) => {
    setCursor(date)
    setView('day')
  }

  return (
    <section className="panel">
      <div className="cal-bar">
        <div className="cal-bar-left">
          <button
            type="button"
            className="icon-btn"
            aria-label={`Previous ${view}`}
            onClick={() => step(-1)}
          >
            ‹
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label={`Next ${view}`}
            onClick={() => step(1)}
          >
            ›
          </button>
          <h2 className="cal-title">{title}</h2>
        </div>

        <div className="cal-bar-right">
          <button
            type="button"
            className="btn"
            onClick={() => setCursor(new Date())}
          >
            Today
          </button>
          <PeriodPicker view={view} cursor={cursor} onPick={setCursor} />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setEditing('new')}
          >
            New appointment
          </button>
          <div className="seg" role="group" aria-label="Calendar view">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`seg-btn${view === item.id ? ' is-active' : ''}`}
                aria-pressed={view === item.id}
                onClick={() => setView(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {view === 'month' && (
        <MonthView
          cursor={cursor}
          today={today}
          byDay={byDay}
          onPickDay={openDay}
          onOpen={setEditing}
        />
      )}
      {view === 'week' && (
        <WeekView
          cursor={cursor}
          today={today}
          byDay={byDay}
          onPickDay={openDay}
          onOpen={setEditing}
        />
      )}
      {view === 'day' && (
        <DayView cursor={cursor} byDay={byDay} onOpen={setEditing} />
      )}

      {editing && (
        <AppointmentForm
          appointment={editing === 'new' ? null : editing}
          defaultDate={cursor}
          cases={cases}
          onClose={() => setEditing(null)}
          onDelete={editing === 'new' ? null : remove}
          onSubmit={save}
        />
      )}
    </section>
  )
}

export default Appointments
