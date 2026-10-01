"""Auth/session state, shared across every page.

This is a personal kiosk device, not a multi-tenant web app, so there is no visible
login/password UI. The backend API still models everything as "a user with an email and
password" (that contract stays intact — nothing about the FastAPI side changes), but this
layer synthesizes a random, invisible device identity once on first run and stores it in
QSettings (Qt's equivalent of localStorage) alongside the resulting token. The only thing
a person ever gives is their details, answering MAYA's one-time setup questions.
"""

import secrets
import uuid

from PySide6.QtCore import QObject, QSettings, Signal

from app.api_client import ApiError, api_client
from app.config import APP_NAME, APP_ORG


class Session(QObject):
    logged_in = Signal(dict)  # profile dict
    needs_setup = Signal()  # first run on this device — no account exists yet
    profile_updated = Signal(dict)

    def __init__(self):
        super().__init__()
        self.profile: dict | None = None
        self._settings = QSettings(APP_ORG, APP_NAME)

    # ---------------- device identity (invisible to the user) ----------------

    def _device_credentials(self) -> tuple[str, str] | None:
        email = self._settings.value("device/email")
        password = self._settings.value("device/password")
        if email and password:
            return email, password
        return None

    def _create_device_credentials(self) -> tuple[str, str]:
        # NOT .local/.test/.invalid/.example — those are on email-validator's reserved-TLD
        # blocklist and the backend's 422 on them, confirmed by testing this directly.
        email = f"device-{uuid.uuid4().hex}@maya-device.app"
        password = secrets.token_urlsafe(32)
        self._settings.setValue("device/email", email)
        self._settings.setValue("device/password", password)
        return email, password

    # ---------------- bootstrap (runs once at app startup) ----------------

    def bootstrap(self) -> None:
        token = self._settings.value("auth/token")
        if token:
            api_client.set_token(token)
            try:
                self.profile = api_client.get_profile()
                self.logged_in.emit(self.profile)
                return
            except ApiError:
                pass  # token expired/invalid — fall through to a silent re-login

        creds = self._device_credentials()
        if creds:
            try:
                result = api_client.login(*creds)
                self._store_token_and_load_profile(result["access_token"])
                return
            except ApiError:
                pass  # stored device credentials no longer work — treat as first run

        # complete_setup() reuses a saved token, so a dead one mustn't survive into setup.
        self._settings.remove("auth/token")
        api_client.set_token(None)
        self.needs_setup.emit()

    def _store_token_and_load_profile(self, token: str) -> None:
        self._settings.setValue("auth/token", token)
        api_client.set_token(token)
        self.profile = api_client.get_profile()
        self.logged_in.emit(self.profile)

    def complete_setup(self, details: dict) -> None:
        """Called once MAYA's first-run questions are answered. Creates the invisible device
        account behind the scenes, then saves the rest of the answers to the profile.

        If the account got created but saving the answers failed (say the backend restarted
        in between), a retry reuses that account instead of registering another one."""
        token = self._settings.value("auth/token")
        if not token:
            email, password = self._create_device_credentials()
            token = api_client.register(email, password, details["name"], details["class_level"])["access_token"]
            self._settings.setValue("auth/token", token)
        api_client.set_token(token)
        api_client.update_profile(**details)
        self._store_token_and_load_profile(token)

    def save_details(self, details: dict) -> None:
        """Editing details later (from onboarding or the dashboard) — no re-greeting."""
        api_client.update_profile(**details)
        self.refresh_profile()

    def refresh_profile(self) -> None:
        self.profile = api_client.get_profile()
        self.profile_updated.emit(self.profile)


session = Session()
