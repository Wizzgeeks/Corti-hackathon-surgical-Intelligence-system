import { useCallback, useRef } from 'react'
import { useDictation } from '../lib/useDictation.js'

const BAR_COUNT = 14

const mmss = (total) =>
  `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(
    total % 60,
  ).padStart(2, '0')}`

/**
 * Inline dictation: an equaliser, then Dictate / Pause / Stop.
 *
 * Text is handed to `onText(finals, interim)` as Corti produces it — nothing
 * is recorded or kept, so there is no file and no playback.
 */
function DictationControls({ onText, onStart, onStop, language = 'en' }) {
  const barsRef = useRef([])

  // Written straight to the DOM: at 60fps this would otherwise re-render the
  // whole field (and its textarea) on every frame.
  const paintLevels = useCallback((levels, paused) => {
    const step = Math.floor(levels.length / BAR_COUNT) || 1
    barsRef.current.forEach((bar, index) => {
      if (!bar) return
      if (paused) {
        bar.style.transform = 'scaleY(0.08)'
        return
      }
      let sum = 0
      for (let i = 0; i < step; i += 1) sum += levels[index * step + i] ?? 0
      const level = sum / step / 255
      bar.style.transform = `scaleY(${Math.max(0.08, level * 1.7)})`
    })
  }, [])

  const { status, error, seconds, start, pause, resume, stop } = useDictation({
    language,
    onText,
    onLevels: paintLevels,
  })

  const active = status === 'live' || status === 'paused'

  return (
    <div className="dictation">
      <div className={`equaliser eq-inline${status === 'live' ? ' is-live' : ''}`}>
        {Array.from({ length: BAR_COUNT }, (_, index) => (
          <span
            key={index}
            className="eq-bar"
            ref={(node) => {
              barsRef.current[index] = node
            }}
          />
        ))}
      </div>

      {active && <span className="rec-time rec-time-sm">{mmss(seconds)}</span>}

      {status === 'connecting' && <span className="rec-state">Connecting…</span>}

      {!active ? (
        <button
          type="button"
          className="btn"
          disabled={status === 'connecting'}
          onClick={() => {
            onStart?.()
            start()
          }}
        >
          Dictate
        </button>
      ) : (
        <>
          <button
            type="button"
            className="btn"
            onClick={status === 'paused' ? resume : pause}
          >
            {status === 'paused' ? 'Resume' : 'Pause'}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={() => {
              stop()
              onStop?.()
            }}
          >
            Stop
          </button>
        </>
      )}

      {error && <span className="form-error dictation-error">{error}</span>}
    </div>
  )
}

export default DictationControls
