"""Small Google OAuth + Calendar adapter used by the local demo.

OAuth is deliberately server-side: the browser only receives an authorization
URL and the refresh token remains in the backend database.
"""

import json
import secrets
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings


SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]

# Local-development state storage. The state is short-lived and single-use.
# The PKCE verifier must survive the browser round-trip as well as the state.
_oauth_states: Dict[str, Dict[str, str]] = {}


def _client_config() -> Dict[str, Any]:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise RuntimeError("Google OAuth credentials are not configured in .env")
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def create_authorization_url(workspace_id: str) -> str:
    from google_auth_oauthlib.flow import Flow

    state = secrets.token_urlsafe(32)
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    _oauth_states[state] = {
        "workspace_id": workspace_id,
        "code_verifier": flow.code_verifier or "",
    }
    return authorization_url


def consume_oauth_state(state: str) -> Optional[str]:
    data = _oauth_states.pop(state, None)
    return data.get("workspace_id") if data else None


def exchange_code(code: str, state: str) -> Tuple[str, str, str]:
    """Exchange the callback code and return workspace, email, token JSON."""
    from google_auth_oauthlib.flow import Flow

    # Keep the state until the token exchange succeeds. This makes a failed
    # exchange diagnosable instead of turning a retry into "state missing".
    state_data = _oauth_states.get(state)
    if not state_data:
        raise ValueError("OAuth state is missing or has already been used")
    workspace_id = state_data["workspace_id"]

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    if state_data.get("code_verifier"):
        flow.code_verifier = state_data["code_verifier"]
    flow.fetch_token(code=code)
    credentials = flow.credentials
    _oauth_states.pop(state, None)
    # The Calendar-only scope intentionally avoids requesting profile/email
    # permissions. The workspace email remains the connection label.
    return workspace_id, "", credentials.to_json()


def _credentials_from_json(token_json: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_info(json.loads(token_json), scopes=SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    return credentials


def create_calendar_event(
    token_json: str,
    summary: str,
    description: str,
    start_at: str,
    end_at: str,
    attendees: List[str],
) -> Tuple[Dict[str, Any], str]:
    """Create a Calendar event and return the event plus refreshed token JSON."""
    from googleapiclient.discovery import build

    credentials = _credentials_from_json(token_json)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    event_body: Dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_at, "timeZone": "UTC"},
        "end": {"dateTime": end_at, "timeZone": "UTC"},
    }
    clean_attendees = sorted({email.strip() for email in attendees if email.strip()})
    if clean_attendees:
        event_body["attendees"] = [{"email": email} for email in clean_attendees]
    created = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates="all" if clean_attendees else "none",
    ).execute()
    return created, credentials.to_json()


def update_calendar_event(
    token_json: str,
    event_id: str,
    summary: str,
    description: str,
    start_at: str,
    end_at: str,
    attendees: List[str],
) -> Tuple[Dict[str, Any], str]:
    """Update an existing Calendar event and return the event plus refreshed token JSON."""
    from googleapiclient.discovery import build

    credentials = _credentials_from_json(token_json)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    event_body: Dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_at, "timeZone": "UTC"},
        "end": {"dateTime": end_at, "timeZone": "UTC"},
    }
    clean_attendees = sorted({email.strip() for email in attendees if email.strip()})
    event_body["attendees"] = [{"email": email} for email in clean_attendees]
    updated = service.events().patch(
        calendarId="primary",
        eventId=event_id,
        body=event_body,
        sendUpdates="all" if clean_attendees else "none",
    ).execute()
    return updated, credentials.to_json()


def cancel_calendar_event(token_json: str, event_id: str) -> str:
    """Cancel an existing Calendar event and return a refreshed token JSON."""
    from googleapiclient.discovery import build

    credentials = _credentials_from_json(token_json)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    service.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()
    return credentials.to_json()


def event_meet_link(event: Dict[str, Any]) -> Optional[str]:
    for entry in (event.get("conferenceData", {}).get("entryPoints", []) or []):
        if entry.get("entryPointType") == "video":
            return entry.get("uri")
    return None
