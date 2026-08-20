"""Referral Orchestrator — drives the intake pipeline and assembles its output.

Unlike the chat orchestrator, this one does not ask a model what to do next:
the intake pipeline is a fixed sequence, so `next_step()` is plain code. Its
two jobs are

1. **sequencing** — hand control to the next agent in `STEP_ORDER`, detouring
   through the Corti authenticator on a `401` and resuming where it left off;
2. **state handling** — take each agent's reply, map it onto the output fields
   (`map_agent_output`), and once the sequence finishes assemble the final
   JSON (`build_output`).

Agent reply shapes it understands:

* `case_data_extractor` returns a **dict** of patient fields:
  `{"patient_name", "patient_age", "patient_gender", "patient_contact"}`
* every other agent returns **text** — a message that is stored verbatim in
  the output field that agent owns (see `TEXT_FIELD_BY_AGENT`).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from bson import ObjectId

from app.agents.base import Agent, AgentSpec
from app.db.mongodb import get_collection
from app.models import appointment as appointment_model
from app.models import case as case_model
from app.models import surgery as surgery_model

logger = logging.getLogger(__name__)

REFERRAL_ORCHESTRATOR_NAME = "referral_orchestrator"

# Returned as `next_agent` when the pipeline has nothing left to do.
DONE = "done"

AUTH_AGENT = "corti_authenticator"
MAX_AUTH_RETRIES = 2
UNAUTHORIZED = 401

# The intake pipeline, in execution order.
STEP_ORDER: tuple[str, ...] = (
    "referral_document_reader",
    "case_data_extractor",
    "case_summariser",
    "clinical_flag_detector",
    "urgency_assessor",
    "next_action_recommender",
    "pre_consultation_briefer",
)

# Structured reply: the extractor is the only agent returning a dict. These
# are its plain-text fields; `referred_by` is an object and handled separately.
PATIENT_FIELDS: tuple[str, ...] = (
    "patient_name",
    "patient_age",
    "patient_gender",
    "patient_contact",
    "referred_to_consultant",
)

# Text replies: agent name -> the output field its message fills.
TEXT_FIELD_BY_AGENT: dict[str, str] = {
    "case_summariser": "case_summary",
    "clinical_flag_detector": "flags",
    "next_action_recommender": "recommendation",
    # Urgency is not part of the response contract below; it is kept in state
    # so the API layer can still surface it.
    "urgency_assessor": "urgency_summary",
    # Not in the response contract; kept in state for the consultation record.
}

# The response contract, in order. Every key is always present.
OUTPUT_FIELDS: tuple[str, ...] = (
    "patient_name",
    "patient_age",
    "patient_gender",
    "patient_contact",
    "referred_to_consultant",
    "referred_by",
    "case_summary",
    "flags",
    "recommendation",
)

# What a completed run looks like. The agents are not executable yet, so this
# is the reference shape — illustrative content, not produced by a real run.
SAMPLE_OUTPUT: dict[str, Any] = {
    "patient_name": "John Doe",
    "patient_age": "62",
    "patient_gender": "Male",
    "patient_contact": "+44 7700 900123",
    "referred_by": {
        "name": "Dr A Smith",
        "current_role": "General Practitioner",
        "organization": "Oakfield Surgery",
    },
    "referred_to_consultant": "Mr R Chandru",
    "case_summary": (
        "62-year-old man with six months of progressive right knee pain, worse "
        "on stairs and after standing. No trauma. Background of hypertension. "
        "Conservative management with analgesia and physiotherapy has not "
        "relieved symptoms."
    ),
    "flags": (
        "Unintentional weight loss of 6 kg over three months (high) — not "
        "explained by the presenting complaint. Night pain disturbing sleep "
        "(medium). No red flags for infection or fracture."
    ),
    "recommendation": (
        "Arrange weight-bearing knee X-ray and routine bloods before the first "
        "appointment. Book into the next orthopaedic clinic; flag the weight "
        "loss for review at booking."
    ),
}


# Markers wrapping the per-agent trace, so one step is easy to grep out of a
# busy log.
FLOW_START = "agent flow output ---------->"
FLOW_END = "agent flow output end  --------->"

# Never write these into the log.
REDACTED_KEYS = frozenset({"corti_access_token"})


def _loggable(value: Any, key: str | None = None) -> Any:
    """Value as it should appear in logs: secrets masked, bulk text trimmed.

    Recurses, because a secret can arrive nested — an agent's raw reply is
    itself carried in state, so masking only the top level would still print
    the Corti token.
    """
    if key in REDACTED_KEYS:
        return "***redacted***" if value else None
    if isinstance(value, dict):
        return {k: _loggable(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_loggable(v) for v in value]
    if isinstance(value, str) and len(value) > 300:
        return f"{value[:300]}… ({len(value)} chars)"
    return value


def log_agent_flow(state: dict) -> None:
    """Log the agent that just ran, its output, and the resulting state."""
    agent = state.get("last_agent")
    if not agent:
        return

    logger.warning(FLOW_START)
    logger.warning("agent      : %s", agent)
    logger.warning(
        "output     : %s",
        json.dumps(_loggable(state.get("last_agent_output")), indent=2, default=str),
    )
    logger.warning("state after: %s", json.dumps(_loggable(state), indent=2, default=str))
    log_output_fields(state, header="contract so far")
    logger.warning(FLOW_END)


def log_output_fields(source: dict, header: str) -> None:
    """Log every field of the response contract, one line each.

    Reads from `source`, so it works on the live state mid-run and on the
    assembled output at the end — the point being that a blank field is
    visible as a blank, rather than absent from the log.
    """
    logger.warning("%s:", header)
    for field in OUTPUT_FIELDS:
        value = source.get(field, "")
        if isinstance(value, dict):
            rendered = ", ".join(f"{k}={v!r}" for k, v in value.items())
        else:
            rendered = "" if value in (None, "") else str(value)
        logger.warning("  %-22s = %s", field, rendered)


# Fields that are objects rather than text.
REFERRER_FIELDS: tuple[str, ...] = ("name", "current_role", "organization")


def empty_output() -> dict[str, Any]:
    """The response contract with every field blank."""
    output: dict[str, Any] = {field: "" for field in OUTPUT_FIELDS}
    output["referred_by"] = {field: "" for field in REFERRER_FIELDS}
    return output


@dataclass(frozen=True)
class Decision:
    """A routing decision, plus whether it ends the run in failure."""

    next_agent: str
    reason: str
    is_failure: bool = False

    def to_update(self) -> dict:
        """Partial state update this decision implies."""
        update: dict = {"next_agent": self.next_agent, "routing_reason": self.reason}
        if self.is_failure:
            update["errors"] = [f"{REFERRAL_ORCHESTRATOR_NAME}: {self.reason}"]
            update["last_error"] = {
                "agent": REFERRAL_ORCHESTRATOR_NAME,
                "message": self.reason,
                "status_code": None,
            }
        return update


def is_unauthorized(state: dict) -> bool:
    """True when the most recent agent failure was an auth rejection."""
    return (state.get("last_error") or {}).get("status_code") == UNAUTHORIZED


def next_step(state: dict) -> Decision:
    """Choose the next agent. Deterministic — no model involved."""
    # 1. Nothing to work with -> stop before spending a call. A `referral_id`
    #    counts: the document reader resolves the stored PDF from it.
    if not any(
        (
            (state.get("referral_text") or "").strip(),
            state.get("document_path"),
            state.get("referral_id"),
        )
    ):
        return Decision(
            DONE,
            "No referral id, document, or text supplied; nothing to triage.",
            is_failure=True,
        )

    # 2. A 401 -> re-authenticate, then resume the agent that failed.
    if is_unauthorized(state):
        retries = state.get("auth_retry_count", 0)
        if retries >= MAX_AUTH_RETRIES:
            return Decision(
                DONE,
                f"Corti authentication failed {retries} times; stopping the run.",
                is_failure=True,
            )
        failed = (state.get("last_error") or {}).get("agent")
        return Decision(
            AUTH_AGENT,
            f"{failed or 'An agent'} returned 401; re-authenticating "
            f"(attempt {retries + 1} of {MAX_AUTH_RETRIES}).",
        )

    # 3. Any other failure -> stop rather than carry a broken state forward.
    if state.get("last_error"):
        error = state["last_error"]
        return Decision(
            DONE,
            f"{error.get('agent')} failed: {error.get('message')}",
            is_failure=True,
        )

    # 4. No Corti session yet -> authenticate first.
    if not state.get("corti_access_token"):
        return Decision(AUTH_AGENT, "No Corti token in state; authenticating first.")

    # 5. Resume an interrupted step, else advance through the sequence.
    pending = state.get("pending_step")
    if pending:
        return Decision(pending, f"Re-authenticated; resuming {pending}.")

    done = set(state.get("completed_agents") or [])
    for step in STEP_ORDER:
        if step not in done:
            return Decision(step, f"Next in sequence: {step}.")

    return Decision(DONE, "All intake agents complete.")


def map_agent_output(agent: str, reply: Any) -> dict:
    """Map one agent's reply onto state fields.

    The extractor returns a dict of patient fields; everyone else returns a
    text message destined for a single field.
    """
    if agent == "case_data_extractor":
        if isinstance(reply, dict):
            mapped = {f: str(reply.get(f, "") or "") for f in PATIENT_FIELDS}
            # The referrer keeps its object shape — it is a person, a role and
            # an organisation, not one string.
            if reply.get("referred_by"):
                mapped["referred_by"] = reply["referred_by"]
            return mapped
        return {}

    field = TEXT_FIELD_BY_AGENT.get(agent)
    if not field or reply is None:
        return {}

    message = str(reply).strip()

    # The summariser opens with a one-line title above a blank line. A case
    # has no title any more, so only the body is kept.
    if agent == "case_summariser" and "\n\n" in message:
        _, _, body = message.partition("\n\n")
        return {"case_summary": body.strip()}

    return {field: message}


def build_output(state: dict) -> dict[str, Any]:
    """Assemble the final response from whatever the agents produced.

    Always returns every field in `OUTPUT_FIELDS`; anything an agent did not
    supply comes back blank rather than being omitted, so callers can rely on
    the shape. Object fields (`referred_by`) keep their structure — only text
    fields are coerced to strings.
    """
    output = empty_output()
    for field in OUTPUT_FIELDS:
        value = state.get(field)
        if value in (None, ""):
            continue
        output[field] = value if isinstance(value, dict) else str(value)
    return output


class ReferralOrchestrator(Agent):
    """Runs the referral intake pipeline and returns one JSON payload.

    It is the first agent called and the one control returns to after every
    step. On each turn it names the next agent (`next_step`); once the
    sequence completes it assembles `referral_output` from the fields the
    agents filled in.

    `run()` should:

    1. fold the previous agent's reply into state with `map_agent_output()`;
    2. call `next_step()` and apply `Decision.to_update()`;
    3. when the decision is `DONE`, add `build_output(state)` as
       `referral_output`.

    `SAMPLE_OUTPUT` in this module shows the shape and level of detail a
    completed run is expected to produce.
    """

    async def load_case_context(self, state: dict) -> dict:
        """Fetch the case, its appointments and its surgeries from Mongo.

        Done here rather than in each agent: one set of queries per run, and
        every agent then reasons over the same records. Loaded once — the flag
        stops the lookup repeating on each turn of the loop.
        """
        case_id = state.get("case_id")
        if not case_id or state.get("case_context_loaded"):
            return {}

        if not ObjectId.is_valid(case_id):
            logger.warning("case_id %r is not a valid ObjectId; skipping.", case_id)
            return {"case_context_loaded": True}

        oid = ObjectId(case_id)
        case = await get_collection(case_model.COLLECTION).find_one({"_id": oid})
        if not case:
            logger.warning("No case %s; agents will run without case context.", case_id)
            return {"case_context_loaded": True}

        appointments = (
            await get_collection(appointment_model.COLLECTION)
            .find({"case": oid})
            .sort("start_time", 1)
            .to_list(length=100)
        )
        surgeries = (
            await get_collection(surgery_model.COLLECTION)
            .find({"case": oid})
            .to_list(length=100)
        )

        logger.info(
            "Loaded case %s: %d appointment(s), %d surgery(ies).",
            case_id,
            len(appointments),
            len(surgeries),
        )
        return {
            "case_document": case,
            "appointment_documents": appointments,
            "surgery_documents": surgeries,
            "case_context_loaded": True,
        }

    async def run(self, state: dict) -> dict:
        """Sequence the pipeline and, on the last turn, assemble the output.

        Mapping each agent's reply into state happens in the workflow's node
        wrapper (via `map_agent_output`), so by the time control is back here
        the fields are already populated.
        """
        # Control is back here after an agent ran: trace what it produced and
        # the state it left behind before choosing the next step.

        log_agent_flow(state)

        # Load the case records before dispatching anything, so the first
        # agent already has them.
        case_context = await self.load_case_context(state)
        state = {**state, **case_context}

        decision = next_step(state)
        update = {**case_context, **decision.to_update()}

        if decision.next_agent == DONE and not decision.is_failure:
            output = build_output(state)
            update["referral_output"] = output
            logger.warning(FLOW_START)
            log_output_fields(output, header="final referral output")
            logger.warning(FLOW_END)

        logger.info("referral routing -> %s (%s)", decision.next_agent, decision.reason)
        return update

    spec = AgentSpec(
        name=REFERRAL_ORCHESTRATOR_NAME,
        title="Referral Orchestrator",
        purpose=(
            "Drive the referral intake sequence, map each agent's reply into "
            "state, and return the assembled referral JSON."
        ),
        consumes=(
            "referral_text",
            "document_path",
            "completed_agents",
            "pending_step",
            "corti_access_token",
            "auth_retry_count",
            "last_error",
        ),
        produces=(
            "next_agent",
            "routing_reason",
            "referral_output",
            *OUTPUT_FIELDS,
            "errors",
            "last_error",
        ),
    )
