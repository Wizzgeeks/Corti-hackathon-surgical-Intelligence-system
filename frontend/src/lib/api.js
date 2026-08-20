/** Triage results, plus the local cache of the latest one. */

import { withLoading } from './loading.js'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const UPLOAD_PATH = import.meta.env.VITE_UPLOAD_PATH ?? '/upload_referrals'
const CASES_PATH = import.meta.env.VITE_CASES_PATH ?? '/cases'
const TEAMS_PATH = '/consultant_teams'
const APPOINTMENTS_PATH = '/appointments'
const CONTACTS_PATH = '/contacts'

const url = (path, params) => {
  const query = new URLSearchParams(
    Object.entries(params ?? {}).filter(([, value]) => value != null && value !== ''),
  ).toString()
  return `${BASE_URL}${path}${query ? `?${query}` : ''}`
}

export const LATEST_CASE_KEY = 'referral_triage.latest_case'

/** The case fields the triage API will return. Everything the UI reads is
 *  here, so a response missing a key still produces a complete record. */
export const CASE_FIELDS = [
  'patient_name',
  'patient_age',
  'patient_gender',
  'patient_contact',
  'allergies',
  'clinical_background',
  'referrer_name',
  'referrer_role',
  'referrer_organization',
  'case_summary',
  'flags',
  'recommendation',
  'pre_consultation_details',
  'notes',
]

/** Not case content, but POST /cases needs them, so they survive the
 *  normalise -> cache -> reload round trip alongside the editable fields. */
export const META_FIELDS = ['referral_id', 'pdf_content']

export const emptyCase = () =>
  Object.fromEntries(CASE_FIELDS.map((key) => [key, '']))

/** Flatten one API value to the string the form controls edit.
 *  List-valued fields (allergies, flags) arrive as arrays; joining keeps
 *  them editable as one line and readable in the detail view. */
const toText = (value) => {
  if (value == null) return ''
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        item && typeof item === 'object'
          ? (item.label ?? item.name ?? item.value ?? item.description ?? '')
          : item,
      )
      .filter((item) => item != null && String(item).trim() !== '')
      .join(', ')
  }
  return String(value)
}

/** Keep only the known fields, as strings — the form controls are all
 *  value-driven and would go uncontrolled on a null or undefined. */
export const normaliseCase = (data) => {
  // /upload_referrals wraps the case fields in `triage` alongside upload
  // metadata (referral_id, stored_path, ...); a bare record is accepted too.
  const source = data?.triage ?? data ?? {}

  // The API sends the referrer as a nested object:
  //   referred_by: { name, current_role, organization }
  // The UI edits the three parts as separate fields, so flatten it here.
  // Already-flat values win, which is what makes a saved (edited) record
  // round-trip through the cache unchanged.
  const referrer = source.referred_by ?? {}
  const flattened = {
    ...source,
    referrer_name: source.referrer_name ?? referrer.name,
    referrer_role: source.referrer_role ?? referrer.current_role,
    referrer_organization:
      source.referrer_organization ?? referrer.organization,
  }

  const record = Object.fromEntries(
    CASE_FIELDS.map((key) => [key, toText(flattened[key])]),
  )

  // Upload metadata sits at the top level of the response, not inside
  // `triage`, so read it from both.
  for (const key of META_FIELDS) {
    const value = data?.[key] ?? source[key]
    if (value != null) record[key] = toText(value)
  }
  return record
}

/** Pull the error message out of a FastAPI response, which puts it in
 *  `detail`, falling back to raw text for anything else. */
async function errorMessage(response) {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
    return JSON.stringify(body).slice(0, 200)
  } catch {
    const text = await response.text().catch(() => '')
    return text.slice(0, 200)
  }
}

/** POST the referral PDF for triage. Resolves to a normalised case record. */
export async function uploadReferral(file) {
  const body = new FormData()
  body.append('file', file)

  let response
  try {
    response = await fetch(`${BASE_URL}${UPLOAD_PATH}`, { method: 'POST', body })
  } catch (cause) {
    // fetch only rejects on network/CORS failures — the request never
    // reached the server, so say so rather than reporting a status.
    throw new Error(
      `Could not reach the triage API at ${BASE_URL}. Is the backend running?`,
      { cause },
    )
  }

  if (!response.ok) {
    throw new Error(
      `Triage failed (${response.status}). ${await errorMessage(response)}`.trim(),
    )
  }

  return normaliseCase(await response.json())
}

/** Whole numbers go as numbers (the API types age as an int); anything
 *  else is passed through so a value like "6 months" is not lost. */
const asAge = (value) => {
  const text = String(value ?? '').trim()
  return /^\d+$/.test(text) ? Number(text) : text
}

/** Build the POST /cases body from the flat record the UI edits. */
export const toCasePayload = (record) => ({
  patient: {
    name: record.patient_name ?? '',
    age: asAge(record.patient_age),
    gender: record.patient_gender ?? '',
    contact: record.patient_contact ?? '',
    allergies: record.allergies ?? '',
    clinical_background: record.clinical_background ?? '',
  },
  referrer: {
    name: record.referrer_name ?? '',
    role: record.referrer_role ?? '',
    organization: record.referrer_organization ?? '',
  },
  case: {
    case_summary: record.case_summary ?? '',
    flags: record.flags ?? '',
    recommendation: record.recommendation ?? '',
    pre_consultation_details: record.pre_consultation_details ?? '',
    notes: record.notes ?? '',
  },
  pdf_content: record.pdf_content ?? '',
  referral_id: record.referral_id ?? '',
})

/** Create the case from the reviewed triage record. */
export async function createCase(record) {
  return withLoading(async () => {
    let response
    try {
      response = await fetch(`${BASE_URL}${CASES_PATH}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(toCasePayload(record)),
      })
    } catch (cause) {
      throw new Error(
        `Could not reach the API at ${BASE_URL}. Is the backend running?`,
        { cause },
      )
    }

    if (!response.ok) {
      const detail = await errorMessage(response)
      throw new Error(
        `Could not save the case (${response.status}). ${detail}`.trim(),
      )
    }

    return response.status === 204 ? null : response.json()
  })
}

/** Shared GET helper. Delegates to `request` so these calls are de-duplicated
 *  and loader-wrapped like every other one. */
async function getJson(target, what) {
  return request('GET', target, { what: `Loading ${what}` })
}

/** Flags arrive as objects ({label, severity, rationale}); keep the detail
 *  rather than reducing each one to its label. One per line, since the field
 *  is displayed and edited as free text. */
const formatFlags = (value) => {
  if (!Array.isArray(value)) return toText(value)
  return value
    .map((flag) => {
      if (!flag || typeof flag !== 'object') return toText(flag)
      const head = [flag.label, flag.severity && `(${flag.severity})`]
        .filter(Boolean)
        .join(' ')
      return [head, flag.rationale].filter(Boolean).join(' — ')
    })
    .filter((line) => line.trim() !== '')
    .join('\n')
}

/** One row of GET /cases, flattened for the caseload table. */
export const normaliseCaseRow = (row) => {
  const patient = row?.patient ?? {}
  return {
    case_id: row?.case_id ?? '',
    status: toText(row?.status),
    is_urgent: Boolean(row?.is_urgent),
    patient_name: toText(patient.name),
    patient_age: toText(patient.age),
    patient_gender: toText(patient.gender),
  }
}

/** GET /cases — summary rows for the caseload table. */
export async function listCases({ limit = 20, skip = 0, isUrgent } = {}) {
  return withLoading(async () => {
    const data = await getJson(
      url(CASES_PATH, { limit, skip, is_urgent: isUrgent }),
      'the case list',
    )
    return {
      total: data?.total ?? 0,
      limit: data?.limit ?? limit,
      skip: data?.skip ?? skip,
      cases: (data?.cases ?? []).map(normaliseCaseRow),
    }
  })
}

/** GET /cases/{id} — the full case, flattened into the shape the detail
 *  page edits, with consultations resolved against their appointments. */
export const normaliseCaseDetail = (data) => {
  const patient = data?.patient ?? {}
  const referrers = data?.referred_by
  const referrer = (Array.isArray(referrers) ? referrers[0] : referrers) ?? {}

  const appointments = new Map(
    (data?.appointments ?? []).map((item) => [item.appointment_id, item]),
  )

  const consultations = (data?.consultations ?? []).map((item, index) => {
    const appointment = appointments.get(item.appointment_id)
    return {
      id: item.consultation_id ?? `c${index + 1}`,
      appointment_id: item.appointment_id ?? '',
      label: `Consultation ${index + 1}`,
      date: formatDate(appointment?.start_time),
      time: formatTime(appointment?.start_time),
      end_time: formatTime(appointment?.end_time),
      appointment_status: toText(appointment?.status),
      consultant_name: toText(appointment?.consultant?.name),
      consultant_speciality: toText(appointment?.consultant?.speciality),
      // No explicit consultation status in the payload: a written summary
      // is what marks one as done.
      status: toText(item.consultation_summary).trim() ? 'Done' : 'Awaiting',
      pre_consultation_details: toText(item.pre_consultation_details),
      consultation_summary: toText(item.consultation_summary),
      transcription: toText(item.transcription),
    }
  })

  return {
    case_id: data?.case_id ?? '',
    patient_name: toText(patient.name),
    patient_age: toText(patient.age),
    patient_gender: toText(patient.gender),
    patient_contact: toText(patient.contact),
    allergies: toText(patient.allergies),
    clinical_background: toText(patient.clinical_background),
    referrer_name: toText(referrer.name),
    referrer_role: toText(referrer.role ?? referrer.current_role),
    referrer_organization: toText(referrer.organization),
    case_summary: toText(data?.case_summary),
    pre_consultation_details: toText(data?.pre_consultation_details),
    notes: toText(data?.notes),
    consultant_requests: (data?.consultant_requests ?? []).map(
      normaliseConsultantRequest,
    ),
    flags: formatFlags(data?.flags),
    // Structured form, so the page can list flags with their severity
    // instead of rendering one paragraph.
    flags_list: Array.isArray(data?.flags)
      ? data.flags
          .filter((flag) => flag && typeof flag === 'object')
          .map((flag) => ({
            label: toText(flag.label),
            severity: toText(flag.severity),
            rationale: toText(flag.rationale),
          }))
      : [],
    recommendation: toText(data?.recommendation),
    status: toText(data?.status),
    is_urgent: Boolean(data?.is_urgent),
    urgency_reason: toText(data?.urgency_reason),
    referral_document_content: toText(data?.referral_document_content),
    consultations,
    appointments: data?.appointments ?? [],
  }
}

/** ISO timestamp -> HH:MM, blank when absent. */
const formatTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`
}

/** ISO timestamp -> dd/mm/yyyy for the consultation tabs. */
const formatDate = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return [
    String(date.getDate()).padStart(2, '0'),
    String(date.getMonth() + 1).padStart(2, '0'),
    date.getFullYear(),
  ].join('/')
}

/** One consultant request, with its two server-set times pre-formatted. */
export const normaliseConsultantRequest = (item, index) => ({
  request_id: item?.request_id ?? `r${index + 1}`,
  consultant_requests: toText(item?.consultant_requests),
  response: toText(item?.response),
  request_time: item?.request_time ?? null,
  responded_time: item?.responded_time ?? null,
  request_time_text: formatDateTime(item?.request_time),
  responded_time_text: formatDateTime(item?.responded_time),
})

const requestsUrl = (caseId, requestId) =>
  `${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}/consultant_requests` +
  (requestId ? `/${encodeURIComponent(requestId)}` : '')

export async function listConsultantRequests(caseId) {
  const data = await request('GET', requestsUrl(caseId), {
    what: 'Loading consultant requests',
  })
  return (data?.consultant_requests ?? []).map(normaliseConsultantRequest)
}

/** Raise a new request. The server stamps `request_time`. */
export async function createConsultantRequest(caseId, text) {
  const created = normaliseConsultantRequest(
    await request('POST', requestsUrl(caseId), {
      body: { consultant_requests: text ?? '' },
      what: 'Saving the request',
    }),
    0,
  )
  reassessInBackground(caseId)
  return created
}

/** Save one side of an existing request — the request text or the response,
 *  never both. Each has its own Save button, and sending only the edited
 *  field is what keeps the other one's timestamp untouched. */
export async function updateConsultantRequest(caseId, requestId, changes) {
  const updated = normaliseConsultantRequest(
    await request('PATCH', requestsUrl(caseId, requestId), {
      body: changes,
      what: 'response' in changes ? 'Saving the response' : 'Saving the request',
    }),
    0,
  )
  // A consultant's answer is new clinical input, not just bookkeeping.
  reassessInBackground(caseId)
  return updated
}

export async function deleteConsultantRequest(caseId, requestId) {
  const result = await request('DELETE', requestsUrl(caseId, requestId), {
    what: 'Deleting the request',
  })
  reassessInBackground(caseId)
  return result
}

/** ISO timestamp -> "dd/mm/yyyy HH:MM", blank when absent. */
const formatDateTime = (value) => {
  if (!value) return ''
  const date = formatDate(value)
  const time = formatTime(value)
  return time ? `${date} ${time}` : date
}

export async function getCaseDetail(caseId) {
  return withLoading(async () =>
    normaliseCaseDetail(
      await getJson(`${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}`, 'the case'),
    ),
  )
}

/** Flat UI field -> [group, API key] for PATCH /cases/{id}. */
export const PATCH_FIELD_MAP = {
  patient_name: ['patient', 'name'],
  patient_age: ['patient', 'age'],
  patient_gender: ['patient', 'gender'],
  patient_contact: ['patient', 'contact'],
  allergies: ['patient', 'allergies'],
  clinical_background: ['patient', 'clinical_background'],
  referrer_name: ['referrer', 'name'],
  referrer_role: ['referrer', 'role'],
  referrer_organization: ['referrer', 'organization'],
  case_summary: ['case', 'case_summary'],
  flags: ['case', 'flags'],
  recommendation: ['case', 'recommendation'],
  pre_consultation_details: ['case', 'pre_consultation_details'],
  notes: ['case', 'notes'],
  status: ['case', 'status'],
  is_urgent: ['case', 'is_urgent'],
  urgency_reason: ['case', 'urgency_reason'],
}

/** Group only the fields that actually changed into the PATCH body.
 *  Sending everything would defeat the point of a partial update — and would
 *  overwrite fields another user edited in the meantime. */
export const toPatchPayload = (before, after) => {
  const body = {}
  for (const [field, [group, key]] of Object.entries(PATCH_FIELD_MAP)) {
    if (!(field in after)) continue
    const next = after[field]
    if (next === before?.[field]) continue
    body[group] ??= {}
    body[group][key] = field === 'patient_age' ? asAge(next) : next
  }
  return body
}

/** PATCH /cases/{id} with just the edits. Resolves to the updated case in
 *  the same shape as getCaseDetail(); null when nothing changed. */
export async function updateCase(caseId, before, after) {
  const body = toPatchPayload(before, after)
  // An empty body is a 400, and "no edits" is not an error worth showing.
  if (Object.keys(body).length === 0) return null

  return withLoading(async () => {
    let response
    try {
      response = await fetch(
        `${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
    } catch (cause) {
      throw new Error(
        `Could not reach the API at ${BASE_URL}. Is the backend running?`,
        { cause },
      )
    }

    if (!response.ok) {
      const detail = await errorMessage(response)
      throw new Error(
        `Could not save the case (${response.status}). ${detail}`.trim(),
      )
    }

    const updated = normaliseCaseDetail(await response.json())
    // Patient and case fields both flow through this PATCH.
    reassessInBackground(caseId)
    return updated
  })
}

// --- shared request helper --------------------------------------------------

/** GETs currently in flight, keyed by URL.
 *
 *  Two things ask for the same data at once: StrictMode double-invokes every
 *  effect in development, and separate components legitimately want the same
 *  list (the teams dropdown, say). Sharing the pending promise collapses
 *  those into one network call. Only GETs — a repeated POST or PATCH is a
 *  distinct write, never a duplicate to fold together.
 */
const inFlight = new Map()

/** One JSON request, with the unreachable-vs-HTTP-error split every caller
 *  needs and the loader held for its duration. */
async function request(method, target, { body, what } = {}) {
  if (method === 'GET') {
    const pending = inFlight.get(target)
    if (pending) return pending
    const promise = sendRequest(method, target, { body, what }).finally(() => {
      inFlight.delete(target)
    })
    inFlight.set(target, promise)
    return promise
  }
  return sendRequest(method, target, { body, what })
}

async function sendRequest(method, target, { body, what } = {}) {
  return withLoading(async () => {
    let response
    try {
      response = await fetch(target, {
        method,
        ...(body === undefined
          ? {}
          : {
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(body),
            }),
      })
    } catch (cause) {
      throw new Error(
        `Could not reach the API at ${BASE_URL}. Is the backend running?`,
        { cause },
      )
    }

    if (!response.ok) {
      const detail = await errorMessage(response)
      throw new Error(`${what} failed (${response.status}). ${detail}`.trim())
    }

    if (response.status === 204 || !response.headers.get('content-length')) {
      // 204, or a body we do not need — DELETE returns nothing.
      const text = await response.text()
      return text ? JSON.parse(text) : null
    }
    return response.json()
  })
}

// --- consultant teams ------------------------------------------------------

export const normaliseTeam = (team) => ({
  consultant_team_id: team?.consultant_team_id ?? '',
  name: toText(team?.name),
  speciality: toText(team?.speciality),
  description: toText(team?.description),
})

export async function listTeams({ limit = 200, skip = 0, q } = {}) {
  const data = await request('GET', url(TEAMS_PATH, { limit, skip, q }), {
    what: 'Loading teams',
  })
  return {
    total: data?.total ?? 0,
    teams: (data?.teams ?? []).map(normaliseTeam),
  }
}

export async function createTeam(team) {
  return normaliseTeam(
    await request('POST', `${BASE_URL}${TEAMS_PATH}`, {
      body: {
        name: team.name,
        speciality: team.speciality ?? '',
        description: team.description ?? '',
      },
      what: 'Creating the team',
    }),
  )
}

export async function updateTeam(teamId, changes) {
  return normaliseTeam(
    await request(
      'PATCH',
      `${BASE_URL}${TEAMS_PATH}/${encodeURIComponent(teamId)}`,
      { body: changes, what: 'Saving the team' },
    ),
  )
}

export async function deleteTeam(teamId) {
  return request(
    'DELETE',
    `${BASE_URL}${TEAMS_PATH}/${encodeURIComponent(teamId)}`,
    { what: 'Deleting the team' },
  )
}

// --- appointments ----------------------------------------------------------

export const normaliseAppointment = (item) => ({
  appointment_id: item?.appointment_id ?? '',
  appointment_type: toText(item?.appointment_type),
  status: toText(item?.status),
  start_time: item?.start_time ?? null,
  end_time: item?.end_time ?? null,
  case_id: item?.case_id ?? '',
  patient_name: toText(item?.patient?.name),
  patient_id: item?.patient?.patient_id ?? '',
  consultant_name: toText(item?.consultant?.name),
  consultant_speciality: toText(item?.consultant?.speciality),
  consultant_team_id: item?.consultant?.consultant_team_id ?? '',
  consultation_id: item?.consultation?.consultation_id ?? '',
  pre_consultation_details: toText(item?.consultation?.pre_consultation_details),
  consultation_summary: toText(item?.consultation?.consultation_summary),
})

/** `from`/`to` are ISO strings bounding start_time — the calendar asks for
 *  the window it is showing rather than the whole book. */
export async function listAppointments({
  from,
  to,
  caseId,
  consultantTeamId,
  limit = 500,
} = {}) {
  const data = await request(
    'GET',
    url(APPOINTMENTS_PATH, {
      from,
      to,
      case_id: caseId,
      consultant_team_id: consultantTeamId,
      limit,
    }),
    { what: 'Loading appointments' },
  )
  return {
    total: data?.total ?? 0,
    appointments: (data?.appointments ?? []).map(normaliseAppointment),
  }
}

export async function createAppointment(input) {
  const created = normaliseAppointment(
    await request('POST', `${BASE_URL}${APPOINTMENTS_PATH}`, {
      body: {
        case_id: input.case_id || undefined,
        patient_id: input.patient_id || undefined,
        consultant_team_id: input.consultant_team_id,
        start_time: input.start_time,
        end_time: input.end_time,
        appointment_type: input.appointment_type ?? 'consultation',
        status: input.status ?? 'scheduled',
        pre_consultation_details: input.pre_consultation_details ?? '',
      },
      what: 'Booking the appointment',
    }),
  )
  reassessInBackground(created.case_id || input.case_id)
  return created
}

export async function updateAppointment(appointmentId, changes) {
  const updated = normaliseAppointment(
    await request(
      'PATCH',
      `${BASE_URL}${APPOINTMENTS_PATH}/${encodeURIComponent(appointmentId)}`,
      { body: changes, what: 'Saving the appointment' },
    ),
  )
  // Consultation fields are edited through the appointment too.
  reassessInBackground(updated.case_id)
  return updated
}

export async function deleteAppointment(appointmentId, caseId) {
  const result = await request(
    'DELETE',
    `${BASE_URL}${APPOINTMENTS_PATH}/${encodeURIComponent(appointmentId)}`,
    { what: 'Deleting the appointment' },
  )
  // The response is empty, so the case has to be named by the caller.
  reassessInBackground(caseId ?? result?.case_id)
  return result
}

// --- dictation -------------------------------------------------------------

/** Short-lived Corti credentials for a dictation session.
 *
 *  The client id and secret never reach the browser — the backend exchanges
 *  them for a token that expires in minutes, and returns the socket URL
 *  already built so the frontend does not hardcode Corti's hosts.
 */
export async function getDictationAuth() {
  return request('GET', `${BASE_URL}/scoped_auth`, { what: 'Starting dictation' })
}

/** Open a Corti interaction and get its diarized stream socket.
 *
 *  Separate from getDictationAuth(): dictation transcribes one voice, this
 *  transcribes a conversation and tags each line with who spoke. */
export async function getConsultationAuth({ caseId, title } = {}) {
  return request('POST', `${BASE_URL}/consultation_auth`, {
    body: { case_id: caseId ?? null, title: title ?? null },
    what: 'Starting the consultation recording',
  })
}

/** Store a consultation transcript and extract its facts, in one call.
 *
 *  Two things happen server-side and the order matters: the transcript is
 *  written first, then Corti's FactsR endpoint is called and its answer saved
 *  as the consultation summary. Doing both here — rather than a save call and
 *  an extract call from the browser — means a dropped connection between them
 *  cannot leave the transcript unsaved. */
export async function extractConsultationFacts(caseId, transcription) {
  const result = await request(
    'POST',
    `${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}/consultation_facts`,
    {
      body: { transcription },
      what: 'Saving the transcript and extracting facts',
    },
  )
  // A consultation summary is new clinical detail; re-grade on it.
  reassessInBackground(caseId)
  return result
}

/** Delete a case and everything attached to it — its consultations,
 *  surgeries, investigations and appointments, and the patient when this was
 *  their last case. */
export async function deleteCase(caseId) {
  return request(
    'DELETE',
    `${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}`,
    { what: 'Deleting the case' },
  )
}

// --- investigations -------------------------------------------------------

const investigationsUrl = (caseId) =>
  `${BASE_URL}${CASES_PATH}/${encodeURIComponent(caseId)}/investigations`

export const normaliseInvestigation = (item) => ({
  investigation_id: item?.investigation_id ?? '',
  name: toText(item?.name),
  summary: toText(item?.summary),
  transcription: toText(item?.transcription),
  reported_at: item?.reported_at ?? null,
  reported_at_text: formatDateTime(item?.reported_at),
})

export async function listInvestigations(caseId) {
  const data = await request('GET', investigationsUrl(caseId), {
    what: 'Loading investigations',
  })
  return (data?.investigations ?? []).map(normaliseInvestigation)
}

/** Upload a report. The backend reads the PDF and summarises it, so this can
 *  take a few seconds — the loader covers it. Multipart, so it goes through
 *  fetch directly rather than the JSON helper. */
export async function uploadInvestigation(caseId, { name, file }) {
  return withLoading(async () => {
    const body = new FormData()
    body.append('name', name)
    body.append('file', file)

    let response
    try {
      response = await fetch(investigationsUrl(caseId), { method: 'POST', body })
    } catch (cause) {
      throw new Error(
        `Could not reach the API at ${BASE_URL}. Is the backend running?`,
        { cause },
      )
    }

    if (!response.ok) {
      const detail = await errorMessage(response)
      throw new Error(
        `Could not add the report (${response.status}). ${detail}`.trim(),
      )
    }

    const data = await response.json()
    // A report is the single most likely thing to change the picture.
    reassessInBackground(caseId)
    return {
      ...normaliseInvestigation(data),
      // The report is stored even when Corti finds no facts, so the caller
      // can show what did not work without treating it as a failure.
      errors: data?.errors ?? [],
    }
  })
}

// --- reassessment after a change -------------------------------------------

/* Any edit to a patient, case, appointment or consultation can change how
   urgent the case is, so every one of them re-runs the urgency agent and then
   reloads the case. The sequence lives here rather than at each call site so
   a new mutation cannot forget it, and so the agent is asked once per change
   however many components triggered it.

   It runs after the write has already succeeded: the edit is saved either
   way, and a grading failure must never surface as "your change did not
   save". Failures are reported to subscribers instead. */

const caseWatchers = new Set()

/** Listen for a reassessed case. Returns the unsubscribe function.
 *
 *  The payload is `{caseId, detail, error}` — `detail` is the reloaded case
 *  when the run succeeded, `error` the reason when it did not. */
export function onCaseReassessed(listener) {
  caseWatchers.add(listener)
  return () => caseWatchers.delete(listener)
}

function announce(payload) {
  caseWatchers.forEach((listener) => {
    try {
      listener(payload)
    } catch {
      // One bad subscriber must not stop the others from updating.
    }
  })
}

/** Re-grade a case's urgency with the Corti agent. */
export async function updateAgentRun(caseId) {
  return request('POST', `${BASE_URL}/update_agent_run`, {
    body: { case_id: caseId },
    what: 'Reassessing urgency',
  })
}

/** Runs in flight, so simultaneous edits to one case coalesce. */
const reassessing = new Map()

/** Re-grade the case, then reload it — the case details only after the agent
 *  run succeeds, since that run is what the reload is meant to show. */
export async function reassessCase(caseId) {
  if (!caseId) return null
  const pending = reassessing.get(caseId)
  if (pending) return pending

  const run = (async () => {
    const agentRun = await updateAgentRun(caseId)
    const detail = await getCaseDetail(caseId)
    return { caseId, agentRun, detail }
  })()
    .then((result) => {
      announce(result)
      return result
    })
    .catch((error) => {
      announce({ caseId, error })
      throw error
    })
    .finally(() => reassessing.delete(caseId))

  reassessing.set(caseId, run)
  return run
}

/** Fire the reassessment without making the caller wait or handle it.
 *
 *  The agent takes several seconds and reaches out to Corti; blocking a save
 *  on it would make every edit feel slow. Subscribers get the fresh case when
 *  it lands. */
function reassessInBackground(caseId) {
  if (!caseId) return
  reassessCase(caseId).catch(() => {
    // Already announced to subscribers; nothing further to do here.
  })
}

export function saveLatestCase(record) {
  try {
    localStorage.setItem(LATEST_CASE_KEY, JSON.stringify(record))
  } catch {
    // Private mode or a full quota — the case is still in memory for this
    // navigation, so a failed write must not block the user.
  }
}

export function loadLatestCase() {
  try {
    const raw = localStorage.getItem(LATEST_CASE_KEY)
    return raw ? normaliseCase(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

// --- contacts --------------------------------------------------------------

export const normaliseContact = (contact) => ({
  contact_id: contact?.contact_id ?? '',
  name: toText(contact?.name),
  role: toText(contact?.role),
  organization: toText(contact?.organization),
})

export async function listContacts({ limit = 200, skip = 0, q } = {}) {
  const data = await request('GET', url(CONTACTS_PATH, { limit, skip, q }), {
    what: 'Loading contacts',
  })
  return {
    total: data?.total ?? 0,
    contacts: (data?.contacts ?? []).map(normaliseContact),
  }
}

export async function createContact(contact) {
  return normaliseContact(
    await request('POST', `${BASE_URL}${CONTACTS_PATH}`, {
      body: {
        name: contact.name,
        role: contact.role ?? '',
        organization: contact.organization ?? '',
      },
      what: 'Creating the contact',
    }),
  )
}

export async function updateContact(contactId, changes) {
  return normaliseContact(
    await request(
      'PATCH',
      `${BASE_URL}${CONTACTS_PATH}/${encodeURIComponent(contactId)}`,
      { body: changes, what: 'Saving the contact' },
    ),
  )
}

export async function deleteContact(contactId) {
  return request(
    'DELETE',
    `${BASE_URL}${CONTACTS_PATH}/${encodeURIComponent(contactId)}`,
    { what: 'Deleting the contact' },
  )
}
