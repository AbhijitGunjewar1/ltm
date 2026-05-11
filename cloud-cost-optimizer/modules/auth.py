"""
Authentication helper – supports service-account JSON key or ADC.
"""

import os
import json
import google.auth
import google.auth.transport.requests
from google.oauth2 import service_account

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/monitoring.read",
    "https://www.googleapis.com/auth/compute.readonly",
]


def get_credentials(credentials_path: str | None = None):
    """Return google.auth credentials, preferring explicit key file."""
    if credentials_path and os.path.exists(credentials_path):
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        print(f"  [auth] Using service-account key: {credentials_path}")
        return creds

    # Fall back to Application Default Credentials
    creds, project = google.auth.default(scopes=SCOPES)
    print(f"  [auth] Using Application Default Credentials (project={project})")
    return creds


def get_access_token(credentials_path: str | None = None) -> str:
    """Return a Bearer token for REST API calls."""
    creds = get_credentials(credentials_path)
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    return creds.token
