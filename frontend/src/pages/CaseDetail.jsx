import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import BookAppointmentDialog from '../components/BookAppointmentDialog.jsx'
import MedicalCoding from '../components/MedicalCoding.jsx'
import AgentThinking from '../components/AgentThinking.jsx'
import QuestionnaireLink from '../components/QuestionnaireLink.jsx'
import Investigations from '../components/Investigations.jsx'
import RecordConsultationDialog from '../components/RecordConsultationDialog.jsx'
import ConsultationSummaryField from '../components/ConsultationSummaryField.jsx'
import ConsultationLetterDialog from '../components/ConsultationLetterDialog.jsx'
import { initials } from '../data/cases.js'
import {
  createCase,
  deleteCase,
  getCaseDetail,
  getMedicalCodes,
  personaliseQuestionnaire,
  patientFormLink,
  reconcileQuestionnaire,
  onCaseReassessed,
  reassessCase,
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

/** True when the agent-graded part of a case is missing.
 *
 *  These four are all written by the same agent run, so any one of them
 *  being blank means that run never landed. */
const needsAgentRun = (data) =>
  Boolean(data?.case_id) &&
  (!data.case_summary?.trim() ||
    !data.recommendation?.trim() ||
    !data.urgency_reason?.trim() ||
    (data.flags_list?.length ?? 0) === 0)

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
  /* The consultation whose recording is open, or null. Separate from
     `recording` so a fresh recording and reviewing an old one cannot both
     be on screen at once. */
  const [openTranscript, setOpenTranscript] = useState(null)
  const [letterFor, setLetterFor] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [linkCopied, setLinkCopied] = useState(false)
  const [reconciling, setReconciling] = useState(false)
  const [consultations, setConsultations] = useState([])
  const [activeTab, setActiveTab] = useState(null)
  const [coding, setCoding] = useState({
    // Which text these codes were produced from; '' means "not fetched yet".
    signature: '',
    codes: [],
    error: '',
    note: '',
  })
  /* Coding reads the summaries the agent run rewrites, so it waits for that
     run rather than racing it. */
  const [agentRunPending, setAgentRunPending] = useState(false)
  /* Set only by the Recode button; the stored codes are used otherwise. */
  const [recoding, setRecoding] = useState(false)
  /* Only whether the form has been settled, and what went wrong if it did
     not — the questions themselves are never shown here. */
  const [quest, setQuest] = useState({ done: false, error: '' })

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
      onCaseReassessed(({ caseId, pending, detail }) => {
        if (caseId !== id) return
        // The run starting, whichever route began it — opening an ungraded
        // case, or saving an edit. The four agent-written sections wait
        // rather than showing what the agents are in the middle of replacing.
        if (pending) {
          setAgentRunPending(true)
          return
        }
        setAgentRunPending(false)
        if (!detail) return
        setDetails(detail)
        setConsultations(detail.consultations ?? [])
      }),
    [id],
  )

  /* What the coding is derived from. Keyed on the summaries themselves so a
     re-render, or an agent run that changed only the urgency, does not send
     the same text to Corti again. */
  const summarySignature = consultations
    .map((item) => (item.consultation_summary ?? '').trim())
    .filter(Boolean)
    .join('\u0000')

  /* Coding runs only once there is something to code, and only after any
     agent run has settled — that run rewrites the case summary the coding
     call sends along as background.

     The result is stamped with the signature it was produced from, so
     "still loading" is derived rather than stored: anything other than the
     current signature means the codes on screen are not for this text. */
  /* Codes the case already carries. An agent run clears them server-side,
     so anything here is current for the summaries on screen. */
  const storedCodes = details?.medical_codes ?? []

  useEffect(() => {
    if (isNew || !summarySignature || agentRunPending) return undefined
    if (coding.signature === summarySignature) return undefined
    // Already coded and saved: nothing to ask Corti for until the next
    // agent run clears them.
    if (storedCodes.length > 0 && !recoding) return undefined

    let cancelled = false
    getMedicalCodes(id, { refresh: recoding })
      .then((result) => {
        if (cancelled) return
        setRecoding(false)
        setCoding({
          signature: summarySignature,
          codes: result.codes,
          error: '',
          note: result.errors?.[0] ?? '',
        })
      })
      .catch((exc) => {
        if (cancelled) return
        setRecoding(false)
        setCoding({
          signature: summarySignature,
          codes: [],
          error: exc.message,
          note: '',
        })
      })
    return () => {
      cancelled = true
    }
  }, [
    id,
    isNew,
    summarySignature,
    agentRunPending,
    coding.signature,
    storedCodes.length,
    recoding,
  ])

  /* Whether this case's form has been worked out already. A case that
     arrives with questions on it has been personalised before. */
  const personalised = (details?.questionnaire_questions ?? []).length > 0

  /* Runs once, when a case that has never had it done is opened — the
     questions are stored precisely so this is not redone on every visit.
     Nothing here renders the questions; the case page only waits for them so
     the link it hands out points at the right form.

     The promise is held rather than a flag, so StrictMode's double-invoke
     subscribes to the one call instead of starting a second. */
  const questRef = useRef(null)

  useEffect(() => {
    if (isNew || !details || personalised || quest.done) return undefined

    if (questRef.current?.caseId !== id) {
      questRef.current = { caseId: id, promise: personaliseQuestionnaire(id) }
    }

    let cancelled = false
    questRef.current.promise
      .then((result) => {
        if (!cancelled) setQuest({ done: true, error: result.errors?.[0] ?? '' })
      })
      .catch((exc) => {
        if (!cancelled) setQuest({ done: true, error: exc.message })
      })
    return () => {
      cancelled = true
    }
  }, [id, isNew, details, personalised, quest.done])

  /* The link is not worth handing out until the form behind it is settled. */
  const questLoading =
    !isNew && Boolean(details) && !personalised && !quest.done

  /* Explicitly asking for the case to be coded again — the only route past
     the stored codes. */
  const recode = () => {
    setRecoding(true)
    setCoding((prev) => ({ ...prev, signature: '' }))
  }

  /* Whatever was fetched this session, else what the case arrived with. */
  const shownCodes = coding.signature ? coding.codes : storedCodes
  const codingLoading =
    Boolean(summarySignature) &&
    coding.signature !== summarySignature &&
    (storedCodes.length === 0 || recoding)

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
        /* A case that arrives without its graded fields has never had a
           successful agent run — or lost it. Run one now and let the
           subscriber above put the result on the page. Fired only from this
           mount effect, so a run that comes back still empty does not
           re-trigger itself. */
        if (needsAgentRun(data)) {
          // `reassessCase` announces both its start and its finish, and the
          // subscriber above turns those into the sections' waiting state.
          reassessCase(id).catch(() => {
            // Silent: the page already shows whatever the case does have.
          })
        }
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
        <h2>{isNew ? 'No referral uploaded' : 'Case not found'}</h2>
        <p>
          {isNew ? (
            <>
              Nothing has been uploaded yet.{' '}
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

  /** Send the answers and the current background to Corti, and take back one
   *  merged brief. The page is refetched so the new background is what is on
   *  screen, rather than a copy of it held here. */
  const reconcile = async () => {
    setSaveError('')
    setReconciling(true)
    try {
      const result = await reconcileQuestionnaire(record.case_id)
      if (result?.errors?.length) setSaveError(result.errors.join(' '))
      await loadCase({ keepTab: true })
    } catch (exc) {
      setSaveError(exc.message)
    } finally {
      setReconciling(false)
    }
  }

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
    let created
    try {
      created = await createCase(draft)
    } catch (exc) {
      // Keep the form open with the user's edits intact so they can retry.
      setSaveError(exc.message)
      return
    }

    // Cache the reviewed values so a reload shows what was actually saved.
    saveLatestCase(draft)
    setDetails(draft)
    setDraft(null)

    /* Straight to the case that was just made. Reviewing a referral and
       opening the case it became are one job, and the case list in between
       is a step back out of it.

       `replace` so Back returns to wherever the referral came from rather
       than to the new-case form, which has nothing left to save. Falls back
       to the list if the API answered without an id — better a list than a
       route to a case that may not exist. */
    if (created?.case_id) {
      navigate(`/cases/${created.case_id}`, { replace: true })
    } else {
      navigate('/cases', { replace: true })
    }
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
            {/* Who the case is about, at a glance — the detail below is for
                reading, this is for knowing whose notes are open. */}
            <p className="case-head-sub">
              {[
                details.patient_age,
                details.patient_gender,
                details.patient_contact,
              ]
                .map((part) => (part ?? '').trim())
                .filter(Boolean)
                .join(' · ') || '—'}
              {details.is_urgent && (
                <span className="sev sev-high case-head-urgent">Urgent</span>
              )}
            </p>
            {/* Who sent the case — reference rather than clinical content, so
                it belongs beside the name and not in the body. */}
            {(details.referrer_name ||
              details.referrer_role ||
              details.referrer_organization) && (
              <p className="case-head-sub case-head-referrer">
                Referred by{' '}
                {[
                  details.referrer_name,
                  details.referrer_role,
                  details.referrer_organization,
                ]
                  .map((part) => (part ?? '').trim())
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            )}
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
                {/* The patient's own form. Copied rather than opened: it is
                    sent to them, not used from here. Personalising the form
                    is waited out in place of the button — the link is not
                    worth sending until it points at the right questions. */}
                {!isNew && (
                  <QuestionnaireLink
                    loading={questLoading}
                    copied={linkCopied}
                    onCopy={async () => {
                      await navigator.clipboard?.writeText(
                        patientFormLink(record.case_id),
                      )
                      setLinkCopied(true)
                      setTimeout(() => setLinkCopied(false), 2000)
                    }}
                  />
                )}
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

        {!isNew && summarySignature && (
          <MedicalCoding
            codes={shownCodes}
            loading={codingLoading}
            error={coding.error}
            note={coding.note}
            onRetry={recode}
          />
        )}

        {!isNew && details.patient_recording_completed && (
          <div className="patient-status">
            <span>
              Patient questionnaire completed
              {details.patient_recording_reconciled
                ? ' and reconciled into the clinical background.'
                : ' — not yet reconciled into the case.'}
            </span>
            <button
              type="button"
              className="btn btn-sm"
              disabled={reconciling}
              onClick={reconcile}
            >
              {reconciling
                ? 'Reconciling…'
                : details.patient_recording_reconciled
                  ? 'Reconciled'
                  : 'Reconcile'}
            </button>
          </div>
        )}

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
            {/* What a clinician opens the case to read comes first; the
                identifying detail below it is reference, not the point. */}
            {!isNew && (
              <>
                {/* Each of these four is written by its own agent, so each
                    waits on its own rather than behind one shared spinner —
                    they finish at different times and the ones already
                    written stay readable. */}
                <div className="prose-pair">
                  <section className="summary-box">
                    <h3 className="detail-title">Case summary</h3>
                    {agentRunPending ? (
                      <AgentThinking agent="summary" />
                    ) : (
                      <Clamped text={details.case_summary} />
                    )}
                  </section>
                  <section className="summary-box summary-box-alt">
                    <h3 className="detail-title">Recommendation</h3>
                    {agentRunPending ? (
                      <AgentThinking agent="recommendation" />
                    ) : (
                      <Clamped text={details.recommendation} />
                    )}
                  </section>
                </div>

                <div className="prose-pair">
                  {agentRunPending ? (
                    <section className="summary-box summary-box-flag">
                      <h3 className="detail-title">Flags</h3>
                      <AgentThinking agent="flags" lines={2} />
                    </section>
                  ) : (
                    <FlagList
                      flags={details.flags_list}
                      fallback={details.flags}
                    />
                  )}
                  <section className="summary-box summary-box-urgency">
                    <h3 className="detail-title">Urgency</h3>
                    {agentRunPending ? (
                      <AgentThinking agent="urgency" lines={2} />
                    ) : (
                      <>
                        <p className="summary-text urgency-line">
                          <span
                            className={`sev sev-${
                              details.is_urgent ? 'high' : 'low'
                            }`}
                          >
                            {details.is_urgent ? 'Urgent' : 'Routine'}
                          </span>
                        </p>
                        {details.urgency_reason && (
                          <Clamped text={details.urgency_reason} lines={4} />
                        )}
                      </>
                    )}
                  </section>
                </div>
              </>
            )}

            <div className="summary-box">
              <h3 className="detail-title">Clinical background</h3>
              <Clamped text={details.clinical_background} />
            </div>
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
                action={
                  active.consultation_summary?.trim() ? (
                    <>
                      {/* Offered once the summary is written and there is a
                          recording behind it to check the summary against. */}
                      {active.transcription?.trim() && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => setOpenTranscript(active)}
                        >
                          View transcript
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setLetterFor(active)}
                      >
                        Download consultation letter
                      </button>
                    </>
                  ) : null
                }
              />
            </div>
          )}

          {/* The saved recording, reopened. The same dialog as a new
              recording, seeded with what was already said, so resuming is
              the control it always was rather than a second code path. */}
          {openTranscript && (
            <RecordConsultationDialog
              key={`${openTranscript.id}-review`}
              caseId={record.case_id}
              initialTranscript={openTranscript.transcription}
              resuming
              doctorName={openTranscript.consultant_name}
              patientName={record.patient_name}
              onClose={() => setOpenTranscript(null)}
            />
          )}

          {/* The letter is written from this consultation, with the case's
              earlier ones as the history behind it — oldest first, which is
              the order they were written in rather than the order the tabs
              show them. */}
          {letterFor && (
            <ConsultationLetterDialog
              key={`${letterFor.id}-letter`}
              caseId={record.case_id}
              consultation={letterFor}
              previousSummaries={consultations
                .filter(
                  (item) =>
                    item.id !== letterFor.id &&
                    item.consultation_summary?.trim(),
                )
                .map((item) => item.consultation_summary)
                .reverse()}
              patient={{
                name: record.patient_name,
                age: record.patient_age,
                gender: record.patient_gender,
                contact: record.patient_contact,
              }}
              onClose={() => setLetterFor(null)}
            />
          )}

          {recording && (
            <RecordConsultationDialog
              caseId={record.case_id}
              /* The consultation on screen is the one being recorded, so its
                 consultant is who is in the room. */
              doctorName={active?.consultant_name ?? ''}
              patientName={record.patient_name}
              onClose={() => {
                // No refetch here: extracting the facts already re-runs the
                // urgency agent, and that run reloads the case itself. The
                // subscriber above puts the result on the page, so fetching
                // again on the way out would only duplicate it.
                setRecording(false)
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
