import { useEffect, useRef, useState } from 'react'
import {
  MONTHS,
  WEEKDAYS,
  addDays,
  formatShort,
  isSameDay,
  monthGrid,
  weeksOfMonth,
} from '../lib/date.js'

/**
 * Period jump control. The picker body depends on the active view:
 *   month → year stepper + month grid
 *   week  → year + month, then the weeks of that month with their date range
 *   day   → a full month calendar
 */
function PeriodPicker({ view, cursor, onPick }) {
  const [open, setOpen] = useState(false)
  const [year, setYear] = useState(cursor.getFullYear())
  const [month, setMonth] = useState(cursor.getMonth())
  const boxRef = useRef(null)

  // Re-sync the draft year/month to the calendar each time we open.
  const toggle = () => {
    if (!open) {
      setYear(cursor.getFullYear())
      setMonth(cursor.getMonth())
    }
    setOpen((prev) => !prev)
  }

  useEffect(() => {
    if (!open) return undefined
    const onDown = (event) => {
      if (!boxRef.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const pick = (date) => {
    onPick(date)
    setOpen(false)
  }

  const label =
    view === 'month' ? 'Go to month' : view === 'week' ? 'Go to week' : 'Go to day'

  return (
    <div className="picker" ref={boxRef}>
      <button
        type="button"
        className="btn"
        aria-expanded={open}
        onClick={toggle}
      >
        {label}
      </button>

      {open && (
        <div className="picker-pop" role="dialog" aria-label={label}>
          <div className="picker-head">
            <button
              type="button"
              className="icon-btn"
              aria-label="Previous year"
              onClick={() => setYear((y) => y - 1)}
            >
              ‹
            </button>
            <span className="picker-year">{year}</span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Next year"
              onClick={() => setYear((y) => y + 1)}
            >
              ›
            </button>
          </div>

          {view === 'month' && (
            <div className="month-grid-pick">
              {MONTHS.map((name, index) => (
                <button
                  key={name}
                  type="button"
                  className={`pick-cell${
                    index === cursor.getMonth() && year === cursor.getFullYear()
                      ? ' is-active'
                      : ''
                  }`}
                  onClick={() => pick(new Date(year, index, 1))}
                >
                  {name.slice(0, 3)}
                </button>
              ))}
            </div>
          )}

          {view === 'week' && (
            <>
              <div className="month-grid-pick">
                {MONTHS.map((name, index) => (
                  <button
                    key={name}
                    type="button"
                    className={`pick-cell${index === month ? ' is-active' : ''}`}
                    onClick={() => setMonth(index)}
                  >
                    {name.slice(0, 3)}
                  </button>
                ))}
              </div>
              <div className="week-list">
                {weeksOfMonth(year, month).map((week) => (
                  <button
                    key={week.index}
                    type="button"
                    className="week-row"
                    onClick={() => pick(week.start)}
                  >
                    <span className="week-name">Week {week.index}</span>
                    <span className="week-range">
                      {formatShort(week.start)} – {formatShort(week.end)}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}

          {view === 'day' && (
            <>
              <div className="picker-months">
                {MONTHS.map((name, index) => (
                  <button
                    key={name}
                    type="button"
                    className={`pick-chip${index === month ? ' is-active' : ''}`}
                    onClick={() => setMonth(index)}
                  >
                    {name.slice(0, 3)}
                  </button>
                ))}
              </div>
              <div className="day-grid-pick">
                {WEEKDAYS.map((day) => (
                  <span key={day} className="day-head">
                    {day.slice(0, 1)}
                  </span>
                ))}
                {monthGrid(new Date(year, month, 1)).map((date) => (
                  <button
                    key={date.toDateString()}
                    type="button"
                    className={`pick-day${
                      date.getMonth() === month ? '' : ' is-muted'
                    }${isSameDay(date, cursor) ? ' is-active' : ''}`}
                    onClick={() => pick(date)}
                  >
                    {date.getDate()}
                  </button>
                ))}
              </div>
            </>
          )}

          <div className="picker-foot">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => pick(addDays(new Date(), 0))}
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default PeriodPicker
