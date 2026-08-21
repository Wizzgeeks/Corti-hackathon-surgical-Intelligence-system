import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { saveLatestCase, uploadReferral } from '../lib/api.js'

const MAX_BYTES = 20 * 1024 * 1024

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const isPdf = (file) =>
  file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')

function NewReferral() {
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const accept = (candidate) => {
    if (!candidate) return
    if (!isPdf(candidate)) {
      setFile(null)
      setError('That file is not a PDF. Please upload a PDF document.')
      return
    }
    if (candidate.size > MAX_BYTES) {
      setFile(null)
      setError('That PDF is larger than 20 MB.')
      return
    }
    setError('')
    setFile(candidate)
  }

  const onDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    accept(event.dataTransfer.files?.[0])
  }

  const clear = () => {
    setFile(null)
    setError('')
    if (inputRef.current) inputRef.current.value = ''
  }

  const onSubmit = async (event) => {
    event.preventDefault()
    if (!file) {
      setError('Please attach the referral PDF before continuing.')
      return
    }

    setError('')
    setSubmitting(true)
    try {
      const record = await uploadReferral(file)
      // Cached so the new-case page survives a refresh, and so the last
      // triage result is still there if the user navigates away and back.
      saveLatestCase(record)
      navigate('/cases/new')
    } catch (exc) {
      setError(exc.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="panel form-panel" onSubmit={onSubmit}>
      <div className="panel-head">
        <div>
          <h2>New referral</h2>
          <p>Upload the referral letter as a PDF to create the case.</p>
        </div>
      </div>

      <div
        className={`dropzone${dragging ? ' is-dragging' : ''}${
          error ? ' is-error' : ''
        }`}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <svg
          className="dropzone-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
          <path d="M14 3v5h5" />
          <path d="M12 17v-6M9.5 13.5 12 11l2.5 2.5" />
        </svg>

        <p className="dropzone-title">Drag and drop the referral PDF here</p>
        <p className="dropzone-sub">PDF only, up to 20 MB</p>

        <button
          type="button"
          className="btn"
          onClick={() => inputRef.current?.click()}
        >
          Choose PDF
        </button>

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

      {file && (
        <div className="file-row">
          <span className="file-badge">PDF</span>
          <span className="file-meta">
            <span className="cell-strong">{file.name}</span>
            <br />
            <span className="cell-sub">{formatSize(file.size)}</span>
          </span>
          <button type="button" className="btn btn-ghost" onClick={clear}>
            Remove
          </button>
        </div>
      )}

      <div className="form-actions">
        <button
          type="button"
          className="btn"
          disabled={submitting}
          onClick={() => navigate('/cases')}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!file || submitting}
        >
          {submitting ? 'Creating case…' : 'Create referral'}
        </button>
      </div>
    </form>
  )
}

export default NewReferral
