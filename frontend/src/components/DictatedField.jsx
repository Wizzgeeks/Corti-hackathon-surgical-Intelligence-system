import { useRef } from 'react'
import DictationControls from './DictationControls.jsx'

/**
 * A textarea that can be typed into or dictated into.
 *
 * Controlled by the parent — this holds no draft of its own, so several of
 * them can sit in one form and be saved together.
 *
 * Dictation writes straight into the field as Corti transcribes: whatever is
 * already there when dictation starts is kept, and speech is appended live.
 * No audio is stored.
 */
function DictatedField({ id, label, value, onChange, placeholder, rows = 4 }) {
  // What the field held when dictation began. Transcripts are laid on top of
  // this, so an interim result Corti later revises does not eat typed text.
  const baseRef = useRef('')

  const applyTranscript = (finals, interim) => {
    const spoken = [finals, interim].filter(Boolean).join(' ').trim()
    const base = baseRef.current
    onChange(base ? `${base}\n\n${spoken}` : spoken)
  }

  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <textarea
        id={id}
        className="textarea"
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="field-actions">
        <DictationControls
          onText={applyTranscript}
          onStart={() => {
            baseRef.current = (value ?? '').trim()
          }}
        />
      </div>
    </div>
  )
}

export default DictatedField
