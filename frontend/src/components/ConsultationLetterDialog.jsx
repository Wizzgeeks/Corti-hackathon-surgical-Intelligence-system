import { useEffect, useRef, useState } from 'react'
import { createConsultationLetter } from '../lib/api.js'

/** The date as it is typed on a letter, not as a table sorts it. */
const letterDate = () =>
  new Date().toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

/**
 * The consultation letter: drafted by the agent, corrected here, printed.
 *
 * The draft is deliberately not stored — it is written from what is on screen,
 * including a summary the clinician has edited but not saved, so a kept copy
 * would go stale the moment the consultation did. What leaves this dialog is
 * the PDF the browser prints.
 *
 * Printing is the browser's own dialog rather than a generated file: it gives
 * the clinician the page setup and the "Save as PDF" they already know, and
 * keeps a letterhead we can style in CSS rather than lay out by hand.
 */
function ConsultationLetterDialog({
  caseId,
  consultation,
  previousSummaries,
  patient,
  onClose,
}) {
  const [letter, setLetter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const textareaRef = useRef(null)

  const consultantName = consultation?.consultant_name ?? ''
  const consultantRole = consultation?.consultant_speciality ?? ''
  // Fixed when the dialog opens: a letter dated mid-edit would be odd.
  const [dated] = useState(letterDate)

  // The letter is written once, from the consultation as it stood when the
  // dialog opened — held in a ref so a re-render of the case behind it cannot
  // send the draft the clinician is editing back through the agent.
  const material = useRef({
    current_consultation_summary: consultation?.consultation_summary ?? '',
    previous_consultation_summaries: previousSummaries ?? [],
    patient: {
      name: patient?.name ?? '',
      // The case detail carries age as text; the API wants a number or
      // nothing at all rather than an empty string.
      age: Number(patient?.age) || null,
      gender: patient?.gender ?? '',
      contact: patient?.contact ?? '',
    },
    consultant_name: consultantName,
    consultant_role: consultantRole,
  })

  /* The request itself, not just its result.
   *
   *  StrictMode runs this effect twice in development. A `cancelled` flag
   *  alone only discards the second *answer* — both calls have already gone
   *  out, and each one is a Corti agent writing a letter. Holding the promise
   *  means the second run subscribes to the first call instead of making
   *  another, so the letter is drafted once however many times the effect
   *  runs. POSTs are not de-duplicated in `api.js` by design — a repeated
   *  write is normally a real second write — so it is handled here.
   */
  const draftRef = useRef(null)

  useEffect(() => {
    let cancelled = false

    if (draftRef.current?.caseId !== caseId) {
      draftRef.current = {
        caseId,
        promise: createConsultationLetter(caseId, material.current),
      }
    }

    draftRef.current.promise
      .then((result) => {
        if (cancelled) return
        setLetter(result.letter)
        if (result.errors?.length) setError(result.errors.join(' '))
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [caseId])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Consultation letter"
      onClick={onClose}
    >
      <div
        className="modal modal-wide letter-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel-head">
          <div>
            <h2>Consultation letter</h2>
            <p className="cell-sub">
              A draft. Correct anything that is wrong before you print it.
            </p>
          </div>
          <div className="letter-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={loading || !letter.trim()}
              onClick={() => window.print()}
            >
              Download PDF
            </button>
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        {loading ? (
          <p className="cell-sub">Writing the letter…</p>
        ) : (
          <textarea
            ref={textareaRef}
            className="input letter-textarea"
            value={letter}
            spellCheck
            onChange={(event) => setLetter(event.target.value)}
            aria-label="Letter text"
          />
        )}

        {/* What actually goes on the page. Off-screen until the print CSS
            takes over, so the letterhead is composed once rather than being
            reassembled by whatever prints it. */}
        <article className="letter-sheet" aria-hidden="true">
          <header className="letter-head">
            <p className="letter-consultant">{consultantName || '—'}</p>
            {consultantRole && <p className="letter-role">{consultantRole}</p>}
            <p className="letter-date">{dated}</p>
          </header>
          <p className="letter-body">{letter}</p>
        </article>
      </div>
    </div>
  )
}

export default ConsultationLetterDialog
