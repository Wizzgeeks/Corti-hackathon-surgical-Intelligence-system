export const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Local-time YYYY-MM-DD key. Avoids the UTC shift of toISOString(). */
export const toKey = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate(),
  ).padStart(2, '0')}`

export const startOfDay = (date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate())

export const addDays = (date, count) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate() + count)

export const addMonths = (date, count) =>
  new Date(date.getFullYear(), date.getMonth() + count, 1)

/** Monday-based start of the week containing `date`. */
export const startOfWeek = (date) => {
  const day = (date.getDay() + 6) % 7
  return addDays(startOfDay(date), -day)
}

export const endOfWeek = (date) => addDays(startOfWeek(date), 6)

export const isSameDay = (a, b) => toKey(a) === toKey(b)

export const isSameMonth = (a, b) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()

export const formatShort = (date) =>
  `${date.getDate()} ${MONTHS[date.getMonth()].slice(0, 3)}`

export const formatLong = (date) =>
  `${WEEKDAYS[(date.getDay() + 6) % 7]}, ${date.getDate()} ${
    MONTHS[date.getMonth()]
  } ${date.getFullYear()}`

/** Six-week grid (42 days) covering the month, Monday-aligned. */
export const monthGrid = (date) => {
  const first = new Date(date.getFullYear(), date.getMonth(), 1)
  const start = startOfWeek(first)
  return Array.from({ length: 42 }, (_, i) => addDays(start, i))
}

/** The weeks of a month, as {index, start, end} — a week belongs to the month
 *  that contains its Monday-aligned first day overlap. */
export const weeksOfMonth = (year, month) => {
  const first = new Date(year, month, 1)
  const last = new Date(year, month + 1, 0)
  const weeks = []
  let cursor = startOfWeek(first)
  while (cursor <= last) {
    weeks.push({
      index: weeks.length + 1,
      start: cursor,
      end: addDays(cursor, 6),
    })
    cursor = addDays(cursor, 7)
  }
  return weeks
}
