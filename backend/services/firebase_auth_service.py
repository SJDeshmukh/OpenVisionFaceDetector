"""Firebase Authentication token verification for web sign-in."""

import json
import os
from pathlib import Path


class FirebaseAuthConfigurationError(RuntimeError):
    """Raised when Firebase Admin cannot be initialized securely."""


class FirebaseAuthTokenError(ValueError):
    """Raised when the supplied token is invalid or is not a Google login."""


def _firebase_app():
    project_id = str(os.environ.get("FIREBASE_PROJECT_ID") or "").strip()
    if not project_id:
        raise FirebaseAuthConfigurationError("FIREBASE_PROJECT_ID is not configured")

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as exc:
        raise FirebaseAuthConfigurationError("firebase-admin is not installed") from exc

    if firebase_admin._apps:
        return firebase_admin.get_app()

    inline_json = str(os.environ.get("FIREBASE_CREDENTIALS_JSON") or "").strip()
    if inline_json:
        try:
            credential = credentials.Certificate(json.loads(inline_json))
        except (TypeError, ValueError) as exc:
            raise FirebaseAuthConfigurationError("FIREBASE_CREDENTIALS_JSON is invalid") from exc
    else:
        credential_path = Path(
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "firebase-credentials.json"
        )
        if not credential_path.is_file():
            raise FirebaseAuthConfigurationError(
                "Firebase service-account credentials are not configured"
            )
        credential = credentials.Certificate(str(credential_path))

    return firebase_admin.initialize_app(credential, {"projectId": project_id})


def verify_google_firebase_token(id_token):
    """Verify a Firebase ID token and require the Google sign-in provider."""
    token = str(id_token or "").strip()
    if not token or len(token) > 20_000:
        raise FirebaseAuthTokenError("A valid Google sign-in token is required")

    try:
        from firebase_admin import auth
        decoded = auth.verify_id_token(token, app=_firebase_app(), check_revoked=False)
    except FirebaseAuthConfigurationError:
        raise
    except Exception as exc:
        raise FirebaseAuthTokenError("Google sign-in could not be verified") from exc

    provider = str((decoded.get("firebase") or {}).get("sign_in_provider") or "")
    email = str(decoded.get("email") or "").strip().lower()
    subject = str(decoded.get("uid") or decoded.get("sub") or "").strip()
    if provider != "google.com":
        raise FirebaseAuthTokenError("Use the Google provider to sign in")
    if decoded.get("email_verified") is not True or not email:
        raise FirebaseAuthTokenError("Your Google email address is not verified")
    if not subject:
        raise FirebaseAuthTokenError("Google account identifier is missing")

    return {
        "subject": subject,
        "email": email,
        "name": str(decoded.get("name") or "").strip(),
        "picture": str(decoded.get("picture") or "").strip(),
    }
