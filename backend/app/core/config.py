from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Referral Triage API"
    host: str = "127.0.0.1"
    port: int = 8000
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "corti_hackathon_opbook360"

    # Origins the browser frontend is served from (Vite dev server).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    upload_dir: str = "storage/uploads"
    max_upload_mb: int = 25

    # --- Corti ---
    corti_client_id: str = ""
    corti_client_secret: str = ""
    corti_environment: str = "eu"  # eu | us
    corti_tenant_name: str = "base"  # also the auth realm
    corti_scope: str = "openid"
    corti_timeout_seconds: float = 60.0
    # Override the derived hosts only if Corti gives you a non-standard one.
    corti_auth_base_url: str | None = None
    corti_api_base_url: str | None = None
    corti_models_base_url: str = "https://ai.eu.corti.app/v1"
    # Language Corti generates structured documents in.
    corti_output_language: str = "en"
    # Retention policy header sent with document generation. "none" keeps
    # referral text out of Corti's storage.
    corti_retention_policy: str = "none"
    # Corti agentic agents, created in the Console and addressed by id.
    corti_urgency_agent_id: str = "d8a2e8a1-496d-4a55-a4cf-629ab61519f2"
    corti_case_summary_agent_id: str = "a8f527e0-ec46-4809-96d0-6afcf21ed199"
    corti_flag_agent_id: str = "7dcc2ffa-ff50-4aa7-88d7-bbe126d75f62"
    corti_next_action_agent_id: str = "e1f26bf9-dc7c-419f-a29b-52ec35d26d85"
    # Testing switch: answer from a canned response instead of calling
    # the agent.
    corti_urgency_agent_dummy: bool = False
    # Agents belong to the Console project that created them, and ours were
    # built under a different project than the clinical APIs use. Set these to
    # that project's credentials; blank falls back to the main pair.
    corti_agent_client_id: str = ""
    corti_agent_client_secret: str = ""

    # --- ElevenLabs (text to speech) ---
    elevenlabs_api_key: str = ""
    # Flash is the low-latency model; the briefing is read on the way in, so
    # waiting on a slower one would defeat the point.
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    # A voice the account can actually use — the shared library is not
    # available on every plan.
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"

    # Template behind the case data extraction document.
    corti_case_extraction_template_id: str = "c7047d5d-eb7d-4a5b-99c0-70d7d66ed6c0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
