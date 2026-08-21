# OpBook360

A clinic workspace for orthopaedic referrals: a referral letter goes in as a
PDF, and what comes out is a case a consultant can work from — graded for
urgency, flagged, summarised, coded, with a personalised patient
questionnaire and a consultation letter at the end of it.

---

## Technology

### Backend

| | |
|---|---|
| Language | Python 3.11+ |
| Web framework | **FastAPI**, served by **Uvicorn** |
| Database | **MongoDB**, via **Motor** (async driver) |
| Validation / models | **Pydantic** + **pydantic-settings** |
| HTTP client | **httpx** (async, used for every outbound Corti call) |
| PDF reading | **pypdf** |
| Tool server | **MCP** (Model Context Protocol) Python SDK |
| AI platform | **Corti** — agents, transcription, fact extraction, coding |

### Frontend

| | |
|---|---|
| Framework | **React 19** |
| Build tool | **Vite 8** |
| Routing | **react-router-dom 7** |
| Dictation | **@corti/dictation-web** |
| Styling | Plain CSS, one stylesheet, CSS custom properties for the theme |

No component library, no CSS framework, no client state library. The app is
small enough that React's own state and a single token-driven stylesheet
carry it.

### Layout

```
backend/
  app/
    apis/            FastAPI routers — one file per resource
    corti_agents/    ← ALL Corti agent execution lives here
    agents/          In-house helper library (PDF reading, case state) — not LangGraph
    graph_workflow/  Dead: LangGraph definitions, imported by nothing
    services/        Corti clients: auth, REST, text generation, coding
    mcp_server/      MCP tool server exposing the case records
    models/          Pydantic + Mongo document models
    db/              Connection and indexes
    core/            Settings
frontend/
  src/
    pages/           One file per screen
    components/      Shared UI
    lib/             API client, dictation hook, helpers
```

---

## Agents

### Where agent execution lives

**Every agent call in this application is made from `backend/app/corti_agents/`.**
That folder is the whole of it. One file per agent, each saying which Corti
agent to talk to and how to phrase the question.

The agents themselves are **built and configured in the Corti Console** — the
Console owns the prompt, the model and the tool wiring. This codebase holds
the agent id and the instruction text, and calls the agent over Corti's
**A2A (agent-to-agent) `message:send`** endpoint.

### LangGraph is not used

There is no LangGraph agent in this application and no LangGraph
orchestration. Nothing in the running system builds a graph, defines nodes or
edges, or hands control to a graph runtime.

`langgraph` still appears in `requirements.txt`, and `app/graph_workflow/`
still contains graph definitions from an earlier approach. **Nothing imports
them** — no router and no startup path touches `graph_workflow`, so no graph
is ever built or run. Treat it as dead code awaiting removal; if you are
tracing how a case gets graded, do not read it.

> **Not to be confused with `app/agents/`.** That folder is a small in-house
> agent library — no LangGraph anywhere in it — and it *is* live: PDF reading
> and case-state assembly for the referral intake and investigation uploads
> go through it. It does not call the Corti Console agents; that is
> `corti_agents` alone.

### The agents

Five Corti Console agents, each reached from its own file:

| Agent | File | What it does |
|---|---|---|
| **Urgency Identifier** | `urgency_identifier.py` | Grades a referral urgent or routine, with a rationale and evidence |
| **Case Summariser** | `case_summariser.py` | Writes the case up in full, as prose and as points |
| **Flag Detector** | `flag_detector.py` | Raises clinical and record-integrity flags with severities |
| **Next Action Recommender** | `next_action_recommender.py` | Says what to do next, reading consultant availability to do it |
| **Consultation Letter Writer** | `consultation_letter_writer.py` | Drafts the letter that follows a consultation |

Agent ids are configuration, not constants — see `corti_*_agent_id` in
`app/core/config.py`, overridable per environment.

### How the agents get their data

The first four **do not receive the case in the request**. They are given an
identifier — a patient name for the urgency agent, a case id for the others —
and reach back into this application's **MCP server** (`app/mcp_server/`) to
read the record themselves. The tools they call:

- `search_patients` / `get_full_patient_record`
- `get_full_case_record`
- `get_consultant_availability`

So an agent works from what is actually stored, rather than from whatever a
prompt-builder chose to send. The consultation letter writer is the exception:
it is handed its material directly, because a letter is written from a
specific consultation rather than from the case as a whole.

### How they are run

`POST /update_agent_run` runs the first four **concurrently** via
`asyncio.gather(..., return_exceptions=True)`. That is the entirety of the
"orchestration": one gather, no graph, no framework.

- The call costs the slowest agent's latency, not the sum.
- One agent failing does not fail the request — its error is reported in
  `errors` and the others' answers are still returned and saved.
- Only every agent failing is a 502.
- Nothing is overwritten with nothing: a missing grade does not clear an
  urgency a clinician set, and an empty write-up does not wipe an existing
  summary.

---

## Corti beyond the agents

Not everything Corti does here is an agent. These are direct API calls, in
`app/services/`:

| Capability | Endpoint | Used for |
|---|---|---|
| **Fact extraction (FactsR)** | `POST /v2/tools/extract-facts` | Reading a referral PDF, an investigation report, and the patient's questionnaire answers into structured facts |
| **Text generation** | `POST /v2/documents/` | Inline single-section documents — used to work out which questionnaire questions a patient still needs asked |
| **Medical coding** | `POST /v2/tools/coding/` | ICD-10-CM codes from the consultation summaries |
| **Live transcription** | `wss://.../audio-bridge/v2/transcribe` | Dictation into a field |
| **Interaction streams** | `wss://` interaction stream | Two-speaker consultation recording, with diarization and named participants |

### Authentication

OAuth2 client credentials. Every Corti call logs in first and sends the token
as a Bearer header; the token is **never persisted**. All of it lives in one
place — `app/services/corti_client.py` — and every URL in
`app/services/corti_endpoints.py`. Add a new Corti call as a method on
`CortiClient`, and its URL to `corti_endpoints.py`.

---

## What the application does

1. **Referral intake** — a PDF is read to text, its facts extracted, and a
   case and patient created.
2. **Agent run** — the four agents grade, summarise, flag and recommend.
   Re-run automatically whenever a case is opened without those fields, and in
   the background after any edit.
3. **Personalised questionnaire** — the clinical background and the standard
   nine questions go to text generation, which returns the numbers of the
   questions still worth asking, capped at four. Stored on the case; the
   patient's link asks only those.
4. **Patient answers** — submitted through a public link, then reconciled into
   the clinical background automatically, with anything the patient supplied
   marked `[from patient's response]`.
5. **Consultation** — recorded live with two-speaker diarization, transcript
   saved, facts extracted into the consultation summary.
6. **Medical coding** — the consultation summaries are coded, stored on the
   case, and re-coded only when an agent run invalidates them.
7. **Consultation letter** — drafted by the letter agent, corrected on screen,
   printed.

---

## Running it

**Backend**

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add CORTI_CLIENT_ID / CORTI_CLIENT_SECRET
uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

**MCP server** — how the agents read the records:

```bash
cd backend
python -m app.mcp_server.server                    # stdio
python -m app.mcp_server.server --transport http   # http on :8080
```

Set `MCP_AUTH_TOKEN` before exposing it beyond localhost; the server refuses
to bind to a non-loopback address without one.

### Configuration

Everything is environment-driven through `app/core/config.py`:

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `MONGO_DB_NAME` | Database |
| `CORTI_CLIENT_ID`, `CORTI_CLIENT_SECRET` | Corti OAuth2 credentials |
| `CORTI_ENVIRONMENT`, `CORTI_TENANT_NAME` | `eu` / `us`, and the auth realm |
| `CORTI_*_AGENT_ID` | Which Console agent each file talks to |
| `CORTI_AGENT_CLIENT_ID/SECRET` | Separate credentials where the agents live in their own Console project |
| `MCP_*` | Transport, host, port, auth token for the tool server |
