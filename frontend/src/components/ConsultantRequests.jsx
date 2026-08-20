import { useState } from 'react'
import DictatedField from './DictatedField.jsx'

/** A card that exists only in the browser until its request is first saved. */
const blankRequest = () => ({
  request_id: `new-${Date.now()}`,
  consultant_requests: '',
  response: '',
  request_time: null,
  responded_time: null,
  request_time_text: '',
  responded_time_text: '',
  isNew: true,
})

/**
 * Questions raised with a consultant, and their replies.
 *
 * The request and the response save separately, each through its own route,
 * so answering a request does not rewrite the question or its timestamp.
 * Both times come back from the server — they are shown here, never sent.
 */
function ConsultantRequests({ requests, onCreate, onUpdate }) {
  const [items, setItems] = useState(requests)
  // Which field is in flight, as `${request_id}:${field}` — the two buttons
  // on a card work independently, so one spinner per card is not enough.
  const [saving, setSaving] = useState('')
  const [errors, setErrors] = useState({})

  const patch = (id, changes) =>
    setItems((prev) =>
      prev.map((item) => (item.request_id === id ? { ...item, ...changes } : item)),
    )

  const setError = (key, message) =>
    setErrors((prev) => ({ ...prev, [key]: message }))

  const save = async (item, field) => {
    const key = `${item.request_id}:${field}`
    setError(key, '')
    setSaving(key)
    try {
      // A card that has never been saved has no server id yet, so its first
      // save has to create the request before a response can attach to it.
      const saved = item.isNew
        ? await onCreate(item.consultant_requests)
        : await onUpdate(item.request_id, {
            [field === 'response' ? 'response' : 'consultant_requests']:
              item[field === 'response' ? 'response' : 'consultant_requests'],
          })

      setItems((prev) =>
        prev.map((entry) =>
          entry.request_id === item.request_id
            ? // Keep the other field's unsaved edits: only the saved side and
              // the server's timestamps are taken from the response.
              {
                ...entry,
                ...saved,
                isNew: false,
                ...(field === 'response'
                  ? { consultant_requests: entry.consultant_requests }
                  : { response: entry.response }),
              }
            : entry,
        ),
      )
    } catch (exc) {
      setError(key, exc.message)
    } finally {
      setSaving('')
    }
  }

  const busy = (item, field) => saving === `${item.request_id}:${field}`
  const errorFor = (item, field) => errors[`${item.request_id}:${field}`]

  return (
    <div className="requests">
      <div className="panel-head">
        <h3 className="detail-title">Consultant requests</h3>
        <button
          type="button"
          className="btn"
          onClick={() => setItems((prev) => [...prev, blankRequest()])}
        >
          New request
        </button>
      </div>

      {items.length === 0 ? (
        <p className="summary-text">No requests raised yet.</p>
      ) : (
        items.map((item, index) => (
          <div className="summary-box request-card" key={item.request_id}>
            <div className="request-head">
              <span className="cell-strong">Request {index + 1}</span>
              <span className="cell-sub">
                {item.request_time_text
                  ? `Requested ${item.request_time_text}`
                  : 'Not saved yet'}
              </span>
            </div>

            <DictatedField
              id={`request-${item.request_id}`}
              label="Request"
              value={item.consultant_requests}
              placeholder="Type, or dictate — speech appears here as you talk."
              onChange={(value) => patch(item.request_id, { consultant_requests: value })}
            />

            <div className="field-actions">
              {errorFor(item, 'request') && (
                <span className="form-error">{errorFor(item, 'request')}</span>
              )}
              <button
                type="button"
                className="btn btn-primary"
                disabled={
                  busy(item, 'request') || !(item.consultant_requests ?? '').trim()
                }
                onClick={() => save(item, 'request')}
              >
                {busy(item, 'request') ? 'Saving…' : 'Save request'}
              </button>
            </div>

            <div className="request-head">
              <span className="cell-sub">
                {item.responded_time_text
                  ? `Responded ${item.responded_time_text}`
                  : 'Awaiting response'}
              </span>
            </div>

            <DictatedField
              id={`response-${item.request_id}`}
              label="Response"
              value={item.response}
              placeholder="Record the consultant's reply…"
              onChange={(value) => patch(item.request_id, { response: value })}
            />

            <div className="field-actions">
              {errorFor(item, 'response') && (
                <span className="form-error">{errorFor(item, 'response')}</span>
              )}
              {item.isNew && (
                <span className="cell-sub">Save the request first.</span>
              )}
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy(item, 'response') || item.isNew}
                onClick={() => save(item, 'response')}
              >
                {busy(item, 'response') ? 'Saving…' : 'Save response'}
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

export default ConsultantRequests
