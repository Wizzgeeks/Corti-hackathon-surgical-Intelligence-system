import Kpi from '../components/Kpi.jsx'
import { KPIS, MIX, PATIENTS_TODAY } from '../lib/dayData.js'

/**
 * Ram's morning, as numbers.
 *
 * Nothing but figures on purpose: this is a board read from across a room at
 * the start of a day, not a worklist to click through. No heading, no date,
 * no greeting — the count of patients, what those patients are, and the
 * KPAs. Nothing else.
 *
 * Static by design — see `lib/dayData.js`.
 */
function MyMorning() {
  return (
    <div className="kpis">
      {/* The headline and its split, together — the four sum to the one, so
          they are read as a whole rather than as five separate figures. */}
      <section className="kpi-hero">
        <Kpi value={PATIENTS_TODAY} label="Patients today" size="xl" />
        <div className="kpi-mix">
          {MIX.map((item) => (
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
        {KPIS.map((item) => (
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

export default MyMorning
