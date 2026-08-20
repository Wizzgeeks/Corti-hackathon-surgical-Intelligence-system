import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import BookAppointmentDialog from '../components/BookAppointmentDialog.jsx'
import ConsultantRequests from '../components/ConsultantRequests.jsx'
import Investigations from '../components/Investigations.jsx'
import RecordConsultationDialog from '../components/RecordConsultationDialog.jsx'
import ConsultationSummaryField from '../components/ConsultationSummaryField.jsx'
import { initials } from '../data/cases.js'
import {
  createCase,
  deleteCase,
  getCaseDetail,
  onCaseReassessed,
  createConsultantRequest,
  updateConsultantRequest,
  loadLatestCase,
  saveLatestCase,
  updateAppointment,
  updateCase,
} from '../lib/api.js'

/** Long prose, collapsed to a readable height with a toggle. Triage
 *  summaries run to a dozen lines; showing them all pushes everything else
 *  off the screen. */
function Clamped({ text, lines = 7 }) {
  const [open, setOpen] = useState(false)
  const value = (text ?? '').trim()

  if (!value) return <p className="summary-text">—</p>

  // Rough threshold: only offer the toggle when it would actually clamp.
  const long = value.length > lines * 90

  return (
    <>
      <p className={`summary-text${long && !open ? ' is-clamped' : ''}`}>
        {value}
      </p>
      {long && (
        <button
          type="button"
          className="link-btn"
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  )
}

/** Flags as separate items with their severity, rather than one paragraph. */
function FlagList({ flags, fallback }) {
  const items = flags ?? []

  if (items.length === 0 && !(fallback ?? '').trim()) {
    return (
      <section className="summary-box summary-box-flag">
        <h3 className="detail-title">Flags</h3>
        <p className="summary-text">No flags raised.</p>
      </section>
    )
  }

  return (
    <section className="summary-box summary-box-flag">
      <h3 className="detail-title">Flags</h3>
      {items.length === 0 ? (
        <Clamped text={fallback} />
      ) : (
        <ul className="flag-list">
          {items.map((flag, index) => (
            <li key={`${flag.label}-${index}`} className="flag-item">
              <span className="flag-head">
                <span className="flag-label">{flag.label || 'Flag'}</span>
                {flag.severity && (
                  <span className={`sev sev-${flag.severity}`}>
                    {flag.severity}
                  </span>
                )}
              </span>
              {flag.rationale && <Clamped text={flag.rationale} lines={3} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** One editable field. `as` picks the control: text input, textarea, or the
 *  consultant dropdown. */
function EditField({
  label,
  name,
  value,
  as = 'input',
  options = [],
  rows = 4,
  onChange,
}) {
  const id = `field-${name}`
  const common = {
    id,
    name,
    value,
    className: 'input',
    onChange: (event) => onChange(name, event.target.value),
  }

  return (
    <div className="edit-field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {as === 'select' ? (
        <select {...common}>
          {/* Keep an unknown saved consultant selectable rather than
              silently switching the case to someone else. */}
          {value && !options.includes(value) && (
            <option value={value}>{value}</option>
          )}
          <option value="">Not assigned</option>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : as === 'textarea' ? (
        <textarea {...common} className="input textarea" rows={rows} />
      ) : (
        <input {...common} type="text" />
      )}
    </div>
  )
}

function CaseDetail({ isNew = false }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [saveError, setSaveError] = useState('')
  const [loadError, setLoadError] = useState('')
  // A new case is whatever the triage API last returned, cached locally by
  // the upload page; a saved case is fetched from GET /cases/{id}.
  const [details, setDetails] = useState(() =>
    isNew ? loadLatestCase() : null,
  )
  // A new case opens straight into edit mode so the triaged values can be
  // corrected before they are saved.
  const [draft, setDraft] = useState(() => {
    const cached = isNew ? loadLatestCase() : null
    return cached ? { ...cached } : null
  })
  const [booking, setBooking] = useState(false)
  const [recording, setRecording] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [consultations, setConsultations] = useState([])
  const [activeTab, setActiveTab] = useState(null)

  // Only the detail endpoint runs here; the list page fetches its own rows.
  const loadCase = useCallback(
    ({ keepTab = false } = {}) =>
      getCaseDetail(id)
        .then((data) => {
          setLoadError('')
          setDetails(data)
          setConsultations(data.consultations ?? [])
          setActiveTab((prev) =>
            keepTab && data.consultations?.some((item) => item.id === prev)
              ? prev
              : (data.consultations?.[0]?.id ?? null),
          )
          return data
        })
        .catch((exc) => setLoadError(exc.message)),
    [id],
  )

  /* Every edit re-runs the urgency agent in the background; the case it
     reloads afterwards arrives here, so the page shows the new grade without
     the user asking for it. A failed run is left silent — the edit itself
     saved, and its own call site reported anything that went wrong. */
  useEffect(
    () =>
      onCaseReassessed(({ caseId, detail }) => {
        if (caseId !== id || !detail) return
        setDetails(detail)
        setConsultations(detail.consultations ?? [])
      }),
    [id],
  )

  useEffect(() => {
    if (isNew) return undefined
    let cancelled = false
    getCaseDetail(id)
      .then((data) => {
        if (cancelled) return
        setLoadError('')
        setDetails(data)
        setConsultations(data.consultations ?? [])
        setActiveTab(data.consultations?.[0]?.id ?? null)
      })
      .catch((exc) => {
        if (!cancelled) setLoadError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [id, isNew])

  if (loadError) {
    return (
      <section className="panel">
        <h2>Case unavailable</h2>
        <p className="form-error" role="alert">
          {loadError}
        </p>
        <p>
          <Link to="/cases">Back to all cases</Link>
        </p>
      </section>
    )
  }

  // The full-screen loader covers the fetch.
  if (!details && !isNew) return null

  const record = details

  if (!record) {
    return (
      <section className="panel">
        <h2>{isNew ? 'No triaged referral' : 'Case not found'}</h2>
        <p>
          {isNew ? (
            <>
              Nothing has been triaged yet.{' '}
              <Link to="/referrals/new">Upload a referral PDF</Link> to start.
            </>
          ) : (
            <>
              No case matches <code>{id}</code>.{' '}
              <Link to="/cases">Back to all cases</Link>
            </>
          )}
        </p>
      </section>
    )
  }

  const active = consultations.find((item) => item.id === activeTab)

  const saveField = async (consultationId, key, value) => {
    const consultation = consultations.find(
      (item) => item.id === consultationId,
    )
    // The consultation record is written through its appointment.
    if (consultation?.appointment_id) {
      await updateAppointment(consultation.appointment_id, { [key]: value })
    }
    setConsultations((prev) =>
      prev.map((item) =>
        item.id === consultationId ? { ...item, [key]: value } : item,
      ),
    )
  }

  const editing = draft !== null
  const setField = (key, value) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  /** Delete the case and everything attached to it, then leave the page —
   *  there is nothing here to come back to. */
  const removeCase = async () => {
    if (
      !window.confirm(
        `Delete this case?\n\nIts consultations, surgeries, investigations and ` +
          `appointments will be deleted too. This cannot be undone.`,
      )
    )
      return

    setSaveError('')
    setDeleting(true)
    try {
      await deleteCase(record.case_id)
      navigate('/cases')
    } catch (exc) {
      setSaveError(exc.message)
      setDeleting(false)
    }
  }

  const saveDetails = async () => {
    if (!isNew) {
      setSaveError('')
      try {
        // Only the changed fields go up; `updated` is the case as the server
        // now holds it, so the page shows what was actually stored.
        const updated = await updateCase(record.case_id, details, draft)
        if (updated) {
          setDetails(updated)
          setConsultations(updated.consultations ?? [])
        } else {
          setDetails(draft)
        }
        setDraft(null)
      } catch (exc) {
        // Keep the form open with the edits intact so they can retry.
        setSaveError(exc.message)
      }
      return
    }

    setSaveError('')
    try {
      await createCase(draft)
    } catch (exc) {
      // Keep the form open with the user's edits intact so they can retry.
      setSaveError(exc.message)
      return
    }

    // Cache the reviewed values so a reload shows what was actually saved.
    saveLatestCase(draft)
    setDetails(draft)
    setDraft(null)
    navigate('/cases')
  }

  return (
    <div className="case-page">
      <section className="panel case-summary">
        <div className="case-head">
          <span className="avatar avatar-lg avatar-soft">
            {initials(details.patient_name)}
          </span>
          <div className="case-head-text">
            <h2>{details.patient_name}</h2>
          </div>
          <div className="case-head-tags">
            {editing ? (
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setDraft(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={saveDetails}
                >
                  Save
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setDraft({ ...details })}
                >
                  Edit
                </button>
                {/* A case that has not been saved yet has nothing to delete. */}
                {!isNew && (
                  <button
                    type="button"
                    className="btn btn-danger"
                    disabled={deleting}
                    onClick={removeCase}
                  >
                    {deleting ? 'Deleting…' : 'Delete case'}
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {saveError && (
          <p className="form-error" role="alert">
            {saveError}
          </p>
        )}

        {editing ? (
          <div className="detail-grid">
            <div>
              <h3 className="detail-title">Patient details</h3>
              <div className="edit-list">
                <EditField
                  label="Name"
                  name="patient_name"
                  value={draft.patient_name}
                  onChange={setField}
                />
                <EditField
                  label="Age"
                  name="patient_age"
                  value={draft.patient_age}
                  onChange={setField}
                />
                <EditField
                  label="Gender"
                  name="patient_gender"
                  value={draft.patient_gender}
                  onChange={setField}
                />
                <EditField
                  label="Contact"
                  name="patient_contact"
                  value={draft.patient_contact}
                  onChange={setField}
                />
                <EditField
                  label="Allergies"
                  name="allergies"
                  value={draft.allergies}
                  onChange={setField}
                />
                {/* Prose, not a value: the referral's facts as Corti grouped
                    them, editable before the case is saved. */}
                <EditField
                  label="Clinical background"
                  name="clinical_background"
                  value={draft.clinical_background}
                  as="textarea"
                  // A grouped brief, not a sentence: it arrives from FactsR
                  // as a couple of dozen lines.
                  rows={16}
                  onChange={setField}
                />
              </div>
            </div>

            <div className="detail-referrer">
              <h3 className="detail-title">Referrer details</h3>
              <div className="edit-list">
                <EditField
                  label="Name"
                  name="referrer_name"
                  value={draft.referrer_name}
                  onChange={setField}
                />
                <EditField
                  label="Role"
                  name="referrer_role"
                  value={draft.referrer_role}
                  onChange={setField}
                />
                <EditField
                  label="Organization"
                  name="referrer_organization"
                  value={draft.referrer_organization}
                  onChange={setField}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="case-read">
            {/* One facts strip: these are all short values, so stacking them
                into narrow columns only made the page taller. */}
            <dl className="facts">
              <div>
                <dt>Age</dt>
                <dd>{details.patient_age || '—'}</dd>
              </div>
              <div>
                <dt>Gender</dt>
                <dd>{details.patient_gender || '—'}</dd>
              </div>
              <div>
                <dt>Contact</dt>
                <dd>{details.patient_contact || '—'}</dd>
              </div>
              <div>
                <dt>Allergies</dt>
                <dd>{details.allergies || '—'}</dd>
              </div>
              <div>
                <dt>Referrer</dt>
                <dd>
                  {details.referrer_name || '—'}
                  {details.referrer_role ? ` · ${details.referrer_role}` : ''}
                  {details.referrer_organization
                    ? ` · ${details.referrer_organization}`
                    : ''}
                </dd>
              </div>
            </dl>

            <div className="summary-box">
              <h3 className="detail-title">Clinical background</h3>
              <Clamped text={details.clinical_background} />
            </div>

            {!isNew && (
              <>
                <div className="prose-pair">
                  <section className="summary-box">
                    <h3 className="detail-title">Case summary</h3>
                    <Clamped text={details.case_summary} />
                  </section>
                  <section className="summary-box summary-box-alt">
                    <h3 className="detail-title">Recommendation</h3>
                    <Clamped text={details.recommendation} />
                  </section>
                </div>

                <FlagList flags={details.flags_list} fallback={details.flags} />

                {/* Keyed on the case so switching cases rebuilds the local
                    draft list rather than carrying the last one over. */}
                <ConsultantRequests
                  key={record.case_id}
                  requests={details.consultant_requests ?? []}
                  onCreate={(text) =>
                    createConsultantRequest(record.case_id, text)
                  }
                  onUpdate={(requestId, changes) =>
                    updateConsultantRequest(record.case_id, requestId, changes)
                  }
                />
              </>
            )}
          </div>
        )}
      </section>

      {/* Reports come in against the case, often before the first visit, so
          they sit above the consultations rather than inside one. */}
      {!isNew && <Investigations caseId={record.case_id} />}

      {/* A freshly triaged case has no consultations booked yet. */}
      {!isNew && (
        <section className="panel consult-panel">
          <div className="panel-head">
            <h2>Consultations</h2>
            <div className="row-actions">
              <button
                type="button"
                className="btn"
                onClick={() => setRecording(true)}
              >
                Record consultation
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setBooking(true)}
              >
                Book appointment
              </button>
            </div>
          </div>

          {consultations.length === 0 && (
            <p>No appointments booked yet for this case.</p>
          )}

          {/* An empty tab strip still draws its underline, which read as a
              stray divider under the empty-state message. */}
          {consultations.length > 0 && (
            <div className="tabs" role="tablist" aria-label="Consultations">
              {consultations.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  id={`tab-${item.id}`}
                  aria-selected={item.id === activeTab}
                  aria-controls={`panel-${item.id}`}
                  className="tab"
                  onClick={() => setActiveTab(item.id)}
                >
                  <span className="tab-date">
                    {item.date || item.label}
                    {item.time ? ` · ${item.time}` : ''}
                  </span>
                  <span className="tab-sub">
                    {item.consultant_name || item.label} ·{' '}
                    <span
                      className={
                        item.status === 'Done' ? 'status-done' : 'status-await'
                      }
                    >
                      {item.status}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}

          {active && (
            <div
              className="tab-panel"
              role="tabpanel"
              id={`panel-${active.id}`}
              aria-labelledby={`tab-${active.id}`}
            >
              <dl className="appt-strip">
                <div>
                  <dt>Consultant</dt>
                  <dd>{active.consultant_name || '—'}</dd>
                </div>
                <div>
                  <dt>Speciality</dt>
                  <dd>{active.consultant_speciality || '—'}</dd>
                </div>
                <div>
                  <dt>Appointment</dt>
                  <dd>
                    {active.date
                      ? `${active.date}${active.time ? ` ${active.time}` : ''}${
                          active.end_time ? `–${active.end_time}` : ''
                        }`
                      : 'Not booked'}
                  </dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{active.appointment_status || '—'}</dd>
                </div>
              </dl>

              <ConsultationSummaryField
                key={`${active.id}-summary`}
                value={active.consultation_summary}
                onSave={(value) =>
                  saveField(active.id, 'consultation_summary', value)
                }
              />
            </div>
          )}

          {recording && (
            <RecordConsultationDialog
              caseId={record.case_id}
              onClose={async () => {
                setRecording(false)
                // Extraction writes the transcript and the summary onto the
                // consultation, so the page is refetched on the way out
                // rather than left showing what it loaded before recording.
                await loadCase({ keepTab: true })
              }}
            />
          )}

          {booking && (
            <BookAppointmentDialog
              caseId={record.case_id}
              patientName={record.patient_name}
              onClose={() => setBooking(false)}
              onBooked={async () => {
                setBooking(false)
                // Refresh so the booking appears as a consultation tab.
                await loadCase({ keepTab: true })
              }}
            />
          )}
        </section>
      )}
    </div>
  )
}

export default CaseDetail
