import { useEffect, useState } from 'react'

/* What each agent is doing, in its own words. Three each at most: past that
   the messages outlast the work and start repeating themselves.
 *
 * The run reports no progress, so these are timed rather than measured —
 * enough to show which agent is working and on what, instead of four
 * identical spinners. */
const AGENT_MESSAGES = {
  summary: [
    'Fetching the case from MCP',
    'Reading the referral and the notes',
    'Summarizing all the info I have',
  ],
  urgency: [
    'Fetching the case from MCP',
    'Weighing what the referral describes',
    'Deciding how soon this needs to be seen',
  ],
  flags: [
    'Reading the notes against the referral',
    'Looking for anything that contradicts',
    'Marking what needs a clinician’s eye',
  ],
  recommendation: [
    'I now have the info',
    'Checking who is free and when',
    'Finding your next best action',
  ],
}

const STAGE_MS = 3200

/**
 * One agent-written section, while its agent is still writing it.
 *
 * Sits inside the section it belongs to rather than over the page: the other
 * three are readable — and often already written — while this one works.
 */
function AgentThinking({ agent, lines = 3 }) {
  const messages = AGENT_MESSAGES[agent] ?? []
  const [stage, setStage] = useState(0)

  useEffect(() => {
    // Holds on the last message rather than looping back to the first,
    // which would read as the agent having started over.
    if (stage >= messages.length - 1) return undefined
    const timer = setTimeout(() => setStage((prev) => prev + 1), STAGE_MS)
    return () => clearTimeout(timer)
  }, [stage, messages.length])

  return (
    <div className="agent-think" role="status" aria-live="polite">
      <p className="agent-think-line">
        <span className="agent-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span className="agent-think-text">{messages[stage]}…</span>
      </p>

      {/* Placeholder prose, so the section keeps roughly the height it will
          have and the case below does not jump when the answer lands. */}
      <div className="agent-skeleton" aria-hidden="true">
        {Array.from({ length: lines }, (_, index) => (
          <span key={index} className="agent-skeleton-line" />
        ))}
      </div>
    </div>
  )
}

export default AgentThinking
