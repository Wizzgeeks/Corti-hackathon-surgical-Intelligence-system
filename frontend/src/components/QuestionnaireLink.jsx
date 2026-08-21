import { useEffect, useState } from 'react'

/* What is happening, in the order it happens. The call reports no progress,
   so these are timed rather than measured — enough to show the wait is work
   and not a hang. */
const STAGES = [
  'Identifying missing information',
  'Creating personalized questionnaires',
  'Formatting it',
]

const STAGE_MS = 2600

/**
 * The patient's form link, and the wait for it.
 *
 * The questions themselves are deliberately not shown: nobody reviews them
 * before sending, and putting nine lines of form on the case page buries
 * what the page is actually for. What a clinician needs here is the link.
 *
 * While the form is being worked out, the staged message stands exactly
 * where the button will be, so the row does not jump when it resolves.
 */
function QuestionnaireLink({ loading, copied, onCopy }) {
  const [stage, setStage] = useState(0)

  useEffect(() => {
    if (!loading) return undefined
    // Holds on the last stage rather than looping: starting the list over
    // would read as the work having restarted.
    if (stage >= STAGES.length - 1) return undefined
    const timer = setTimeout(() => setStage((prev) => prev + 1), STAGE_MS)
    return () => clearTimeout(timer)
  }, [loading, stage])

  if (loading) {
    return (
      <span className="quest-wait" role="status" aria-live="polite">
        <span className="spinner spinner-sm" aria-hidden="true" />
        <span className="quest-wait-text">{STAGES[stage]}…</span>
      </span>
    )
  }

  return (
    <button type="button" className="btn" onClick={onCopy}>
      {copied ? 'Link copied' : 'Copy patient form link'}
    </button>
  )
}

export default QuestionnaireLink
