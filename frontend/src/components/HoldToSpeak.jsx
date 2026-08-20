import { useCallback, useEffect, useRef } from 'react'
import { useDictation } from '../lib/useDictation.js'

const BAR_COUNT = 24

/**
 * Press-and-hold microphone, with the level meter above the field it fills.
 *
 * Held rather than toggled: on a phone, holding is unambiguous about when it
 * is listening, and letting go is the whole gesture. Speech is appended to
 * whatever is already in the answer, so a patient can add to it in several
 * goes.
 *
 * `target` names the field being dictated into and is handed back with every
 * transcript. Corti sends the closing segment a couple of seconds *after* the
 * microphone is released, by which time the form may have moved on — without
 * the target, that last piece of speech lands in whichever field is showing
 * by then.
 */
function HoldToSpeak({ value, target, onChange, disabled }) {
  const barsRef = useRef([])
  // What the answer held when this turn of speaking began — transcripts are
  // laid on top of it, so a revised interim result cannot eat earlier text.
  const baseRef = useRef('')
  // The field this turn of speaking belongs to, captured when it started.
  const targetRef = useRef(target)

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
      bar.style.transform = `scaleY(${Math.max(0.08, (sum / step / 255) * 1.7)})`
    })
  }, [])

  const applyTranscript = useCallback(
    (finals, interim) => {
      const spoken = [finals, interim].filter(Boolean).join(' ').trim()
      if (!spoken) return
      const base = baseRef.current
      onChange(base ? `${base} ${spoken}` : spoken, targetRef.current)
    },
    [onChange],
  )

  const { status, error, start, stop } = useDictation({
    onText: applyTranscript,
    onLevels: paintLevels,
  })

  const live = status === 'live' || status === 'paused'

  // Leaving the question mid-sentence stops the microphone; the words already
  // spoken still land on the question they were spoken for.
  useEffect(() => {
    if (live && targetRef.current !== target) stop()
    // Only reacts to the field changing, not to every status tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])

  const busy = status === 'connecting'

  const begin = (event) => {
    if (disabled || live || busy) return
    // Stops the press turning into a text selection or a scroll.
    event.preventDefault()
    baseRef.current = (value ?? '').trim()
    targetRef.current = target
    start()
  }

  const end = () => {
    if (live) stop()
  }

  return (
    <div className="speak">
      <div className={`equaliser eq-speak${status === 'live' ? ' is-live' : ''}`}>
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

      <div className="speak-controls">
        <button
          type="button"
          className={`mic${live ? ' is-live' : ''}`}
          disabled={disabled || busy}
          aria-label="Hold to speak your answer"
          onPointerDown={begin}
          onPointerUp={end}
          onPointerLeave={end}
          onPointerCancel={end}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3z" />
            <path d="M6 11a6 6 0 0 0 12 0M12 17v3" />
          </svg>
        </button>
        <span className="speak-hint">
          {busy
            ? 'Connecting…'
            : live
              ? 'Listening — let go when you have finished'
              : 'Hold to speak'}
        </span>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export default HoldToSpeak
