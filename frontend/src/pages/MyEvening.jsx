import Kpi from '../components/Kpi.jsx'
import {
  CONSULTANT,
  EVENING_EXCEPTIONS,
  OUTCOMES,
  PATIENTS_CONSULTED,
} from '../lib/dayData.js'

const longDate = (value) =>
  value.toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })

/**
 * Ram's evening, as numbers.
 *
 * The morning board read backwards: what the day amounted to rather than what
 * is coming. Figures only, and no list to click through — by the evening the
 * question is "what did that add up to", and anything worth opening again has
 * already been opened.
 *
 * The headline is the count of patients consulted, the three beneath it are
 * where those patients went, and the two at the foot are what the day left
 * behind.
 *
 * Static by design — see `lib/dayData.js`.
 */
function MyEvening() {
  return (
    <div className="kpis">
      <header className="kpis-head">
        <p className="day-eyebrow">{longDate(new Date())}</p>
        <h2 className="day-title">That was the day, Ram</h2>
        <p className="day-sub">
          {CONSULTANT.speciality} · {CONSULTANT.clinic}
        </p>
      </header>

      {/* The headline and its split, together — the three sum to the one, so
          they are read as a whole rather than as four separate figures. */}
      <section className="kpi-hero">
        <Kpi value={PATIENTS_CONSULTED} label="Patients consulted" size="xl" />
        <div className="kpi-mix">
          {OUTCOMES.map((item) => (
            <Kpi
              key={item.key}
              value={item.value}
              label={item.label}
              size="lg"
            />
          ))}
        </div>
      </section>

      <section className="kpi-grid">
        {EVENING_EXCEPTIONS.map((item) => (
          <Kpi
            key={item.key}
            value={item.value}
            unit={item.unit}
            label={item.label}
            tone={item.tone}
          />
        ))}
      </section>
    </div>
  )
}

export default MyEvening
