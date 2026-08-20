import { useRef, useState } from 'react'
import { uploadInvestigation } from '../lib/api.js'

const MAX_BYTES = 20 * 1024 * 1024

const isPdf = (file) =>
  file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Add an investigation report.
 *
 * The upload does the work server-side — the PDF is read and its facts pulled
 * out — so this stays open until it comes back, and reports the reason if the
 * report was stored but could not be summarised.
 */
function AddInvestigationDialog({ caseId, onClose, onAdded }) {
  const inputRef = useRef(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const accept = (candidate) => {
    if (!candidate) return
    if (!isPdf(candidate)) {
      setFile(null)
      setError('That file is not a PDF.')
      return
    }
    if (candidate.size > MAX_BYTES) {
      setFile(null)
      setError('That PDF is larger than 20 MB.')
      return
    }
    setError('')
    setFile(candidate)
    // Saves retyping what the file is already called.
    if (!name.trim()) setName(candidate.name.replace(/\.pdf$/i, ''))
  }

  const submit = async (event) => {
    event.preventDefault()
    if (!name.trim()) return setError('Give the report a name.')
    if (!file) return setError('Attach the report PDF.')

    setError('')
    setSaving(true)
    try {
      const added = await uploadInvestigation(caseId, { name: name.trim(), file })
      // Stored either way; only the summary can come back empty.
      if (added.errors?.length) {
        setError(added.errors.join(' '))
        return
      }
      onAdded(added)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <div className="panel-head">
          <div>
            <h2>Add report</h2>
            <p className="cell-sub">
              The PDF is read and summarised when it is uploaded.
            </p>
          </div>
        </div>

        <div className="edit-field">
          <label className="field-label" htmlFor="investigation-name">
            Name
          </label>
          <input
            id="investigation-name"
            className="input"
            value={name}
            placeholder="MRI right knee"
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        <div className="edit-field">
          <span className="field-label">Report</span>
          <div className="file-row">
            <button
              type="button"
              className="btn"
              onClick={() => inputRef.current?.click()}
            >
              {file ? 'Choose another PDF' : 'Choose PDF'}
            </button>
            {file && (
              <span className="file-meta">
                <span className="cell-strong">{file.name}</span>{' '}
                <span className="cell-sub">{formatSize(file.size)}</span>
              </span>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="visually-hidden"
            onChange={(event) => accept(event.target.files?.[0])}
          />
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <div className="form-actions">
          <button
            type="button"
            className="btn"
            disabled={saving}
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={saving || !file || !name.trim()}
          >
            {saving ? 'Reading the report…' : 'Add report'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default AddInvestigationDialog
