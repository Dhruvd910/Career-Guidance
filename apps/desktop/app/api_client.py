"""Sync HTTP client for the FastAPI backend. Mirrors apps/web/src/lib/api.ts endpoint
for endpoint so the desktop app and the (still-present) web app stay behavioral twins of
the same backend. Runs off the Qt UI thread via app.workers.run_async — see that module.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import API_BASE_URL


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.token: str | None = None
        self._client = httpx.Client(base_url=base_url, timeout=30)

    def set_token(self, token: str | None) -> None:
        self.token = token

    def _headers(self, has_json_body: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        if has_json_body:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, json: Any = None, params: dict | None = None, files: Any = None) -> Any:
        has_json_body = json is not None and files is None
        try:
            resp = self._client.request(
                method, path, json=json if has_json_body else None,
                params=params, files=files, headers=self._headers(has_json_body),
            )
        except httpx.RequestError as e:
            raise ApiError(0, f"Could not reach the server: {e}") from e

        if resp.status_code >= 400:
            message = f"Request failed ({resp.status_code})"
            try:
                body = resp.json()
                if isinstance(body.get("detail"), str):
                    message = body["detail"]
            except Exception:
                pass
            raise ApiError(resp.status_code, message)

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Any = None, files: Any = None) -> Any:
        return self._request("POST", path, json=json, files=files)

    def put(self, path: str, json: Any = None) -> Any:
        return self._request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # ---------------- domain methods ----------------

    def register(self, email: str, password: str, name: str, class_level: int) -> dict:
        return self.post("/api/auth/register", {"email": email, "password": password, "name": name, "class_level": class_level})

    def login(self, email: str, password: str) -> dict:
        return self.post("/api/auth/login", {"email": email, "password": password})

    def get_profile(self) -> dict:
        return self.get("/api/student/profile")

    def update_profile(self, **fields) -> dict:
        return self.put("/api/student/profile", {k: v for k, v in fields.items() if v is not None})

    def update_profile_fields(self, fields: dict) -> dict:
        """Like update_profile, but sends None too — for clearing an answer."""
        return self.put("/api/student/profile", fields)

    def add_academic_record(self, **fields) -> dict:
        return self.post("/api/student/academic-record", fields)

    def onboarding_next_step(self) -> dict:
        return self.get("/api/student/onboarding/next-step")

    def list_exams(self) -> list:
        return self.get("/api/exams")

    def save_exam_profile(self, **fields) -> dict:
        return self.post("/api/exams/profile", fields)

    def get_exam_profile(self, exam_code: str) -> dict:
        return self.get(f"/api/exams/{exam_code}/profile")

    # ---- practice papers (MCQ tests taken in the app) ----

    def practice_options(self, exam_code: str) -> dict:
        return self.get("/api/practice/options", {"exam_code": exam_code})

    def start_practice(self, exam_code: str, mode: str, subject: str | None = None) -> dict:
        return self.post("/api/practice/start", {"exam_code": exam_code, "mode": mode, "subject": subject})

    def submit_practice(self, attempt_id: int, answers: list[dict], seconds_taken: int) -> dict:
        return self.post(f"/api/practice/{attempt_id}/submit", {"answers": answers, "seconds_taken": seconds_taken})

    def practice_attempts(self) -> list:
        return self.get("/api/practice/attempts")

    def practice_attempt(self, attempt_id: int) -> dict:
        return self.get(f"/api/practice/attempts/{attempt_id}")

    def create_mock_test(self, **fields) -> dict:
        return self.post("/api/mock-tests", fields)

    def mock_test_history(self, exam_code: str | None = None) -> list:
        return self.get("/api/mock-tests/history", params={"exam_code": exam_code} if exam_code else None)

    def mock_test_dashboard(self, exam_code: str | None = None) -> dict:
        return self.get("/api/mock-tests/dashboard", params={"exam_code": exam_code} if exam_code else None)

    def list_careers(self) -> list:
        return self.get("/api/careers")

    def assessment_questions(self) -> dict:
        return self.get("/api/careers/assessment/questions")

    def career_by_key(self, key: str) -> dict:
        return self.get(f"/api/careers/key/{key}")

    def submit_career_assessment(self, assessment_type: str, responses: dict) -> dict:
        return self.post("/api/careers/assessment", {"assessment_type": assessment_type, "responses": responses})

    def search_colleges(self, **params) -> list:
        return self.get("/api/colleges", params={k: v for k, v in params.items() if v})

    def get_college(self, college_id: int) -> dict:
        return self.get(f"/api/colleges/{college_id}")

    def get_cutoffs(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/cutoffs")

    def get_fees(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/fees")

    def get_hostel(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/hostel")

    def get_placements(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/placements")

    def get_nearby(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/nearby")

    def get_reviews(self, college_id: int) -> list:
        return self.get(f"/api/colleges/{college_id}/reviews")

    def add_review(self, college_id: int, rating: int, text: str, tags: list | None = None) -> dict:
        return self.post(f"/api/colleges/{college_id}/reviews", {"rating": rating, "text": text, "tags": tags or []})

    def compare_colleges(self, college_ids: list[int]) -> dict:
        return self.post("/api/colleges/compare", {"college_ids": college_ids})

    def predict(self, exam_code: str, **fields) -> dict:
        path = "/api/predict/neet" if exam_code == "NEET_UG" else "/api/predict/jee"
        return self.post(path, {"exam_code": exam_code, **fields})

    def preference_list(self, exam_code: str, **fields) -> dict:
        return self.post("/api/counselling/preference-list", {"exam_code": exam_code, **fields})

    def get_roadmap(self) -> dict:
        return self.get("/api/roadmap")

    def list_saved_items(self) -> list:
        return self.get("/api/saved-items")

    def save_item(self, item_type: str, item_id: int, bucket: str | None = None, notes: str | None = None) -> dict:
        return self.post("/api/saved-items", {"item_type": item_type, "item_id": item_id, "bucket": bucket, "notes": notes})

    def delete_saved_item(self, item_id: int) -> None:
        return self.delete(f"/api/saved-items/{item_id}")

    def chat(self, message: str, conversation_id: int | None = None) -> dict:
        return self.post("/api/ai/chat", {"message": message, "conversation_id": conversation_id})

    def speak(self, text: str) -> dict:
        return self.post("/api/ai/speak", {"text": text})

    def transcribe(self, audio_bytes: bytes) -> dict:
        return self._request("POST", "/api/ai/transcribe", files={"audio": ("speech.wav", audio_bytes, "audio/wav")})

    def voice_chat(self, audio_bytes: bytes, conversation_id: int | None = None) -> dict:
        params = {"conversation_id": conversation_id} if conversation_id else None
        return self._request(
            "POST", "/api/ai/voice-chat", params=params,
            files={"audio": ("recording.wav", audio_bytes, "audio/wav")},
        )


api_client = ApiClient()
