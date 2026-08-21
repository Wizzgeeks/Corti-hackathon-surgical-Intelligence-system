import sys
from contextlib import asynccontextmanager
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Allow `python app/main.py`: without this the backend root isn't on sys.path
# and the `app.*` imports below fail.
if __package__ in (None, ""):
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.apis import api_router  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.indexes import ensure_indexes  # noqa: E402
from app.db.mongodb import (  # noqa: E402
    close_mongo_connection,
    connect_to_mongo,
    get_database,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    await ensure_indexes(get_database())
    yield
    await close_mongo_connection()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# The frontend runs on a different origin in development, so the browser
# blocks its requests without this — curl works either way, which is why the
# failure only shows up in the app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    db = get_database()
    await db.command("ping")
    return {"status": "ok", "database": db.name}


if __name__ == "__main__":
    import uvicorn

    backend_root = BACKEND_ROOT

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=[
            str(backend_root / "app" / d)
            for d in (
                "agents",
                "apis",
                "core",
                "corti_agents",
                "db",
                "models",
                "services",
            )
        ],
    )
