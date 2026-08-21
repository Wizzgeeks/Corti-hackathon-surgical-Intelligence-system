import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import HoldToSpeak from '../components/HoldToSpeak.jsx'
import {
  getPatientQuestionnaire,
  submitPatientQuestionnaire,
} from '../lib/api.js'

/**
 * The patient's registration form — the one public page in the app.
 *
 * One question at a time, so a phone screen shows the question and the answer
 * without scrolling, and so the length of the form is not the first thing a
 * patient sees. Answers are kept in memory until the end and submitted in one
 * go; nothing is stored against the case until they say they are done.
 */
function PatientQuestionnaire() {
  const { caseId } = useParams()
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')
  const [answers, setAnswers] = useState({})
  const [step, setStep] = useState(0)
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    let cancelled = false
    getPatientQuestionnaire(caseId)
      .then((data) => {
        if (cancelled) return
        setForm(data)
        setDone(data.completed)
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [caseId])

  if (error) {
    return (
      <main className="patient-page">
        <div className="patient-card">
          <h1>We could not open this form</h1>
          <p className="patient-lead">{error}</p>
          <p className="patient-note">
            Please check the link you were sent, or contact the clinic.
          </p>
        </div>
      </main>
    )
  }

  if (!form) return null

  if (done) {
    return (
      <main className="patient-page">
        <div className="patient-card patient-done">
          <div className="tick" aria-hidden="true">
            ✓
          </div>
          <h1>Thank you{form.patient_name ? `, ${form.patient_name}` : ''}</h1>
          <p className="patient-lead">
            Your answers have been sent to the clinic. There is nothing else to
            do — your specialist will have these before your visit.
          </p>
        </div>
      </main>
    )
  }

  const questions = form.questions
  // The intro counts as the first card, so the questions start at step 1.
  const intro = step === 0
  const current = intro ? null : questions[step - 1]
  const answered = questions.filter((q) => (answers[q.order] ?? '').trim()).length

  const setAnswer = (order, value) =>
    setAnswers((prev) => ({ ...prev, [order]: value }))

  const submit = async () => {
    setError('')
    setSending(true)
    try {
      await submitPatientQuestionnaire(
        caseId,
        questions.map((q) => ({
          order: q.order,
          question: q.question,
          answer: answers[q.order] ?? '',
        })),
      )
      setDone(true)
    } catch (exc) {
      setError(exc.message)
      setSending(false)
    }
  }

  return (
    <main className="patient-page">
      <div className="patient-progress" aria-hidden="true">
        <span style={{ width: `${(step / questions.length) * 100}%` }} />
      </div>

      <div className="patient-card">
        {intro ? (
          <>
            <p className="patient-eyebrow">Registration form</p>
            <h1>
              We received your referral
              {form.referred_by ? ` from ${form.referred_by}` : ''}.
            </h1>
            <p className="patient-lead">
              Before your visit we need a few details from you. Please check
              them and answer the questions below — you can type, or hold the
              microphone and answer by speaking.
            </p>
            <p className="patient-note">
              {questions.length} questions. Nothing is saved until you send
              your answers at the end.
            </p>
            <div className="patient-actions">
              <button
                type="button"
                className="btn btn-primary btn-lg"
                onClick={() => setStep(1)}
              >
                Start
              </button>
            </div>
          </>
        ) : (
          <>
            {/* Position in this patient's form, not the question's number on
                the standard nine — they are only asked a few of them, so the
                stored order jumps and would read as "5 of 4". */}
            <p className="patient-eyebrow">
              Question {step} of {questions.length}
            </p>
            <h1 className="patient-question">{current.question}</h1>

            {/* The order goes down and comes back with each transcript, so a
                closing segment that arrives after the patient has moved on
                still lands on the question they answered. */}
            <HoldToSpeak
              value={answers[current.order] ?? ''}
              target={current.order}
              onChange={(value, order) => setAnswer(order ?? current.order, value)}
            />

            <textarea
              className="textarea patient-answer"
              rows={6}
              value={answers[current.order] ?? ''}
              placeholder="Type your answer, or hold the microphone above."
              aria-label={current.question}
              onChange={(event) => setAnswer(current.order, event.target.value)}
            />

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}

            <div className="patient-actions">
              <button
                type="button"
                className="btn"
                disabled={sending}
                onClick={() => setStep((prev) => prev - 1)}
              >
                Back
              </button>
              {step < questions.length ? (
                <button
                  type="button"
                  className="btn btn-primary btn-lg"
                  onClick={() => setStep((prev) => prev + 1)}
                >
                  {(answers[current.order] ?? '').trim() ? 'Next' : 'Skip'}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-lg"
                  disabled={sending || answered === 0}
                  onClick={submit}
                >
                  {sending ? 'Sending…' : 'Send my answers'}
                </button>
              )}
            </div>

            {step === questions.length && answered === 0 && (
              <p className="patient-note">
                Please answer at least one question before sending.
              </p>
            )}
          </>
        )}
      </div>
    </main>
  )
}

export default PatientQuestionnaire
