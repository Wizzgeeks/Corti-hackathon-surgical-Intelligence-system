import { useState } from 'react'

const FIELD_KEY = 'consultation_summary'

/**
 * What was found, decided and planned during the consultation.
 *
 * Kept separate from the pre-consultation field on purpose: dictation is
 * wired there first, and this one is expected to diverge further.
 */
function ConsultationSummaryField({ value, onSave }) {
  const [draft, setDraft] = useState(value)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const dirty = draft !== value

  const save = async () => {
    setError('')
    try {
      await onSave(draft)
      setSaved(true)
    } catch (exc) {
      setError(exc.message)
    }
  }

  return (
    <div className="field">
      <label className="field-label" htmlFor={FIELD_KEY}>
        Consultation summary
      </label>
      <p className="field-hint">
        Findings, decisions and the plan agreed during the consultation.
      </p>
      <textarea
        id={FIELD_KEY}
        className="textarea"
        rows={5}
        value={draft}
        placeholder="Enter the consultation summary…"
        onChange={(event) => {
          setDraft(event.target.value)
          setSaved(false)
        }}
      />

      <div className="field-actions">
        {error && <span className="form-error">{error}</span>}
        {saved && !dirty && !error && <span className="saved-note">Saved</span>}
        <button
          type="button"
          className="btn btn-primary"
          disabled={!dirty}
          onClick={save}
        >
          Save
        </button>
      </div>
    </div>
  )
}

export default ConsultationSummaryField
