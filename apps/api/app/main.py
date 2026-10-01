from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import ai, auth, careers, colleges, exams, mock_tests, practice, predictions, roadmap, saved_items, student

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Dev convenience: also allow the Next.js dev server when reached via a LAN IP
    # (e.g. from a phone/laptop on the same network as this Pi), not just localhost.
    # Auth uses a Bearer token, not cookies, so allow_credentials=False is correct here
    # and lets us pair a broad regex with allow_origins without violating CORS rules.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}):3000",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(student.router)
app.include_router(exams.router)
app.include_router(mock_tests.router)
app.include_router(practice.router)
app.include_router(careers.router)
app.include_router(colleges.router)
app.include_router(predictions.router)
app.include_router(roadmap.router)
app.include_router(saved_items.router)
app.include_router(ai.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
