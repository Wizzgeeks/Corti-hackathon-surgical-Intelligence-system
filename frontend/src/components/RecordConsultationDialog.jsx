import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDictation } from '../lib/useDictation.js'
import { extractConsultationFacts } from '../lib/api.js'

const BAR_COUNT = 32

const mmss = (total) =>
  `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(
    total % 60,
  ).padStart(2, '0')}`

/** Corti numbers the speakers; the room decides which number is the doctor. */
const labelFor = (speaker, swapped) => {
  const doctorFirst = speaker === 0
  return (doctorFirst ? !swapped : swapped) ? 'Doctor' : 'Patient'
}

const SPEAKER_LINE = /^\s*\[(doctor|patient)\]\s*(.*)$/i

/** Read an edited transcript back into turns.
 *
 *  The inverse of how the turns are written out, so the round trip through
 *  the text box is lossless: a line keeps its speaker, and a line without a
 *  label is treated as a continuation of the one above rather than being
 *  dropped. `swapped` is undone here, or a transcript edited while the
 *  labels were swapped would come back with the speakers reversed.
 */
const parseTurns = (text, swapped) => {
  const turns = []
  for (const line of (text ?? '').split('\n')) {
    const match = line.match(SPEAKER_LINE)
    if (match) {
      const doctor = match[1].toLowerCase() === 'doctor'
      turns.push({
        id: `turn-${turns.length + 1}`,
        speaker: (doctor ? !swapped : swapped) ? 0 : 1,
        text: match[2].trim(),
      })
      continue
    }
    if (!line.trim()) continue
    const last = turns[turns.length - 1]
    if (last) last.text = `${last.text} ${line.trim()}`.trim()
    else turns.push({ id: 'turn-1', speaker: 0, text: line.trim() })
  }
  return turns.filter((turn) => turn.text)
}

/**
 * Live consultation transcript.
 *
 * Corti diarizes the single microphone, so each transcript arrives tagged
 * with a speaker; consecutive segments from the same speaker are merged into
 * one turn, and the interim segment is shown as it is revised. Nothing is
 * recorded — the audio is dropped as it streams.
 */
function RecordConsultationDialog({
  caseId,
  onClose,
  // A transcript already on the consultation. Seeding the turns with it is
  // what turns this dialog into "read what was said, then carry on": the
  // Resume control and the extraction below already work off the turns, so
  // continuing an old recording needs nothing else.
  initialTranscript = '',
  // Titles the dialog for whichever of those two jobs it is doing.
  resuming = false,
  // Who is actually in the room. Sent to Corti with the participants so the
  // stored interaction names them rather than saying "doctor" and "patient".
  doctorName = '',
  patientName = '',
}) {
  const [turns, setTurns] = useState(() => parseTurns(initialTranscript, false))
  const [interim, setInterim] = useState(null)
  // Diarization decides who is speaker 0; only the room knows if that is the
  // consultant, so the labels can be swapped.
  const [swapped, setSwapped] = useState(false)
  // The result of the last extraction: the saved summary, or why it failed.
  const [extraction, setExtraction] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState('')
  // 'structured' is the speaker-by-speaker reading view; 'text' is the same
  // transcript in one editable box.
  const [view, setView] = useState('structured')
  const [text, setText] = useState('')

  // Corti reuses one id for every transcript in a stream, so it cannot key
  // the turns — they get their own counter.
  const turnSeq = useRef(parseTurns(initialTranscript, false).length)
  const barsRef = useRef([])
  const scrollRef = useRef(null)
  // Autoscroll follows the transcript until the reader scrolls up, which
  // would otherwise be undone on the next segment.
  const stickRef = useRef(true)

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

  const addSegment = useCallback(({ text, isFinal, speaker }) => {
    if (!text.trim()) return
    if (!isFinal) {
      setInterim({ speaker, text })
      return
    }
    setInterim(null)
    setTurns((prev) => {
      const last = prev[prev.length - 1]
      // One person speaking for a while arrives as several segments; showing
      // each as its own turn would read as a rally.
      if (last && last.speaker === speaker) {
        return [
          ...prev.slice(0, -1),
          { ...last, text: `${last.text} ${text}`.trim() },
        ]
      }
      turnSeq.current += 1
      return [...prev, { id: `turn-${turnSeq.current}`, speaker, text }]
    })
  }, [])

  /* Memoised: useDictation keeps this in a ref, and a fresh object each
     render would churn it for no reason. */
  const participants = useMemo(
    () => ({ doctor: doctorName, patient: patientName }),
    [doctorName, patientName],
  )

  const { status, error, seconds, start, pause, resume, stop } = useDictation({
    caseId,
    participants,
    // Not dictation: this opens an interaction stream so Corti separates the
    // two voices in the room.
    conversation: true,
    onLevels: paintLevels,
    onSegment: addSegment,
  })

  const live = status === 'live' || status === 'paused'

  useEffect(() => {
    if (view !== 'structured' || !stickRef.current) return
    const node = scrollRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [turns, interim, view])

  const onScroll = () => {
    const node = scrollRef.current
    if (!node) return
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight
    stickRef.current = distance < 40
  }

  /** The turns written out, speaker labels included. */
  const serialiseTurns = () =>
    turns
      .map((turn) => `[${labelFor(turn.speaker, swapped)}] ${turn.text}`)
      .join('\n')

  /** The transcript as it currently stands, wherever it is being edited. */
  const transcriptText = () => (view === 'text' ? text : serialiseTurns())

  const showTextBox = () => {
    setText(serialiseTurns())
    setView('text')
  }

  /** Back to the structured view, keeping whatever was typed in the box. */
  const showStructured = () => {
    setTurns(parseTurns(text, swapped))
    setView('structured')
  }

  /** Recording appends to the turns, so edits have to be folded back in
   *  before the stream can add to them. */
  const record = (resumeStream) => {
    if (view === 'text') showStructured()
    resumeStream()
  }

  // Editing is offered once the conversation has stopped or been paused —
  // never mid-flow, when the next turn would land on top of the edit.
  const canEdit =
    status !== 'live' &&
    status !== 'connecting' &&
    (turns.length > 0 || text.trim())

  /** Save the transcript and pull the facts out of it, in one round trip.
   *
   *  Recording is stopped first — a transcript that is still growing would be
   *  saved half-finished. The backend stores the transcript before it calls
   *  Corti, so a failure here still leaves the consultation on record. */
  const extractFacts = async () => {
    if (live) stop()
    const text = transcriptText()
    if (!text.trim()) return

    setExtracting(true)
    setExtractError('')
    try {
      const result = await extractConsultationFacts(caseId, text)
      // The transcript is saved either way; only the facts can come back
      // empty. A partial result stays on screen with the reason, since
      // closing would hide what went wrong.
      if (result.errors?.length) {
        setExtraction(result)
        setExtractError(result.errors.join(' '))
        return
      }
      // Saved: the case page behind this shows the result, so there is
      // nothing left to do here.
      onClose()
    } catch (err) {
      setExtractError(err.message)
    } finally {
      setExtracting(false)
    }
  }

  const close = () => {
    if (live) stop()
    onClose()
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal modal-wide record-modal">
        {/* The equaliser sits above everything: it is the one signal that the
            microphone is actually being heard. */}
        <div className={`equaliser eq-wide${status === 'live' ? ' is-live' : ''}`}>
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

        <div className="panel-head">
          <div>
            <h2>{resuming ? 'Consultation recording' : 'Record consultation'}</h2>
            <p className="cell-sub">
              {status === 'connecting'
                ? 'Connecting…'
                : live
                  ? `Listening · ${mmss(seconds)}`
                  : resuming
                    ? 'The transcript as recorded. Resume to add to it.'
                    : 'Speech is transcribed live. No audio is stored.'}
            </p>
          </div>
          <div className="row-actions">
            {canEdit && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={view === 'text' ? showStructured : showTextBox}
              >
                {view === 'text' ? 'Show structured' : 'View in textbox'}
              </button>
            )}
            {/* Swapping rewrites the labels, which only exist as labels in
                the structured view — in the box they are just text. */}
            {view === 'structured' && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setSwapped((prev) => !prev)}
              >
                Swap speakers
              </button>
            )}
          </div>
        </div>

        {(error || extractError) && (
          <p className="form-error" role="alert">
            {error || extractError}
          </p>
        )}

        {extraction?.consultation_summary && (
          <div className="summary-block">
            <p className="cell-sub">
              Transcript saved · {extraction.fact_count} fact
              {extraction.fact_count === 1 ? '' : 's'} written to the
              consultation summary
            </p>
            <pre className="summary-text summary-facts">
              {extraction.consultation_summary}
            </pre>
          </div>
        )}

        {view === 'text' ? (
          <textarea
            className="textarea transcript-box"
            value={text}
            aria-label="Consultation transcript"
            placeholder="[Doctor] …&#10;[Patient] …"
            onChange={(event) => setText(event.target.value)}
          />
        ) : (
        <div
          className="transcript"
          ref={scrollRef}
          onScroll={onScroll}
          aria-live="polite"
        >
          {turns.length === 0 && !interim && (
            <p className="summary-text">
              {live
                ? 'Listening — each turn appears once the speaker pauses.'
                : 'Press Start to begin transcribing.'}
            </p>
          )}

          {turns.map((turn) => {
            const label = labelFor(turn.speaker, swapped)
            return (
              <p className={`turn turn-${label.toLowerCase()}`} key={turn.id}>
                <span className="turn-speaker">[{label}]</span>{' '}
                {turn.text}
              </p>
            )
          })}

          {interim && (
            <p
              className={`turn turn-interim turn-${labelFor(
                interim.speaker,
                swapped,
              ).toLowerCase()}`}
            >
              <span className="turn-speaker">
                [{labelFor(interim.speaker, swapped)}]
              </span>{' '}
              {interim.text}
            </p>
          )}
          </div>
        )}

        <div className="form-actions">
          <button type="button" className="btn" onClick={close}>
            Close
          </button>
          {/* Available the moment there is something to save — during
              recording too, since it stops the stream before extracting. */}
          {turns.length > 0 && (
            <button
              type="button"
              className="btn"
              disabled={extracting}
              onClick={extractFacts}
            >
              {extracting ? 'Extracting…' : 'Extract facts'}
            </button>
          )}
          {!live ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={status === 'connecting'}
              onClick={() => record(start)}
            >
              {turns.length ? 'Resume recording' : 'Start recording'}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                onClick={
                  status === 'paused' ? () => record(resume) : pause
                }
              >
                {status === 'paused' ? 'Resume' : 'Pause'}
              </button>
              <button type="button" className="btn btn-danger" onClick={stop}>
                Stop
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default RecordConsultationDialog
