import { useState } from 'react'

const FIELD_KEY = 'consultation_summary'

/**
 * What was found, decided and planned during the consultation.
 *
 * Kept separate from the pre-consultation field on purpose: dictation is
 * wired there first, and this one is expected to diverge further.
 *
 * Reads as prose until someone chooses to edit it. A summary is written
 * once and re-read many times, so the default view is the reading view;
 * an always-open textarea makes settled text look like unfinished input.
 */
function ConsultationSummaryField({ value, onSave, action }) {
  const [draft, setDraft] = useState(value)
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const dirty = draft !== value
  const text = String(value ?? '')

  const startEditing = () => {
    setDraft(value)
    setError('')
    setSaved(false)
    setEditing(true)
  }

  const cancel = () => {
    setDraft(value)
    setError('')
    setEditing(false)
  }

  const save = async () => {
    setError('')
    try {
      await onSave(draft)
      setSaved(true)
      setEditing(false)
    } catch (exc) {
      setError(exc.message)
    }
  }

  return (
    <div className="field">
      <div className="field-head">
        <div>
          <span className="field-label" id={`${FIELD_KEY}-label`}>
            Consultation summary
          </span>
          <p className="field-hint">
            Findings, decisions and the plan agreed during the consultation.
          </p>
        </div>
        {/* `action` is whatever the case page wants offered alongside the
            summary — the recording it was written from, today. */}
        <div className="row-actions">
          {!editing && action}
          {!editing && (
            <button type="button" className="btn btn-sm" onClick={startEditing}>
              {text ? 'Edit' : 'Add summary'}
            </button>
          )}
        </div>
      </div>

      {editing ? (
        <>
          <textarea
            id={FIELD_KEY}
            className="textarea"
            rows={5}
            value={draft}
            autoFocus
            placeholder="Enter the consultation summary…"
            onChange={(event) => {
              setDraft(event.target.value)
              setSaved(false)
            }}
          />

          <div className="field-actions">
            {error && <span className="form-error">{error}</span>}
            <button type="button" className="btn btn-ghost" onClick={cancel}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!dirty}
              onClick={save}
            >
              Save
            </button>
          </div>
        </>
      ) : (
        <>
          {text ? (
            <p className="field-text" aria-labelledby={`${FIELD_KEY}-label`}>
              {text}
            </p>
          ) : (
            <p className="field-empty">No consultation summary yet.</p>
          )}

          <div className="field-actions">
            {error && <span className="form-error">{error}</span>}
            {saved && !dirty && !error && (
              <span className="saved-note">Saved</span>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default ConsultationSummaryField
