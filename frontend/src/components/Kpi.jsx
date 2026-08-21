/**
 * One figure. The number carries the tile; the label sits under it, quiet.
 *
 * Shared by both day pages so a figure is the same object in the morning as
 * it is in the evening — `size` sets how loud it is, `tone` whether it should
 * be scanned past.
 */
function Kpi({ value, unit, label, tone, size }) {
  return (
    <div className={`kpi${tone ? ` kpi-${tone}` : ''}${size ? ` kpi-${size}` : ''}`}>
      <span className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </span>
      <span className="kpi-label">{label}</span>
    </div>
  )
}

export default Kpi
