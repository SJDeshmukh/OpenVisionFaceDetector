"""Firebase Authentication token verification for web sign-in."""

import json
import os
import threading
import time
from pathlib import Path


class FirebaseAuthConfigurationError(RuntimeError):
    """Raised when Firebase Admin cannot be initialized securely."""


class FirebaseAuthTokenError(ValueError):
    """Raised when the supplied token is invalid or is not a Google login."""


_PUBLIC_CERT_REQUEST = None
_PUBLIC_CERT_REQUEST_LOCK = threading.Lock()
_MAX_CLOCK_SKEW_SECONDS = 60


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


def _public_certificate_request():
    """Return a cached HTTP client for Google's Firebase signing certificates."""
    global _PUBLIC_CERT_REQUEST
    if _PUBLIC_CERT_REQUEST is not None:
        return _PUBLIC_CERT_REQUEST

    with _PUBLIC_CERT_REQUEST_LOCK:
        if _PUBLIC_CERT_REQUEST is None:
            try:
                import cachecontrol
                import requests
                from google.auth.transport.requests import Request
            except ImportError as exc:
                raise FirebaseAuthConfigurationError(
                    "Firebase public-key verification dependencies are not installed"
                ) from exc
            session = cachecontrol.CacheControl(requests.Session())
            _PUBLIC_CERT_REQUEST = Request(session=session)
    return _PUBLIC_CERT_REQUEST


def _validate_public_certificate_claims(decoded, project_id, now=None):
    """Apply Firebase's required claims not enforced by google-auth's helper."""
    expected_issuer = f"https://securetoken.google.com/{project_id}"
    if str(decoded.get("iss") or "") != expected_issuer:
        raise FirebaseAuthTokenError("Google sign-in token has an invalid issuer")

    subject = str(decoded.get("sub") or "").strip()
    if not subject or len(subject) > 128:
        raise FirebaseAuthTokenError("Google account identifier is invalid")

    auth_time = decoded.get("auth_time")
    if isinstance(auth_time, bool):
        raise FirebaseAuthTokenError("Google sign-in token has an invalid authentication time")
    try:
        auth_time = int(auth_time)
    except (TypeError, ValueError) as exc:
        raise FirebaseAuthTokenError(
            "Google sign-in token has an invalid authentication time"
        ) from exc
    current_time = int(time.time() if now is None else now)
    if auth_time > current_time + _MAX_CLOCK_SKEW_SECONDS:
        raise FirebaseAuthTokenError("Google sign-in token is not active yet")


def _verify_with_public_certificates(token):
    """Verify a Firebase ID token without a service-account private key."""
    project_id = str(os.environ.get("FIREBASE_PROJECT_ID") or "").strip()
    if not project_id:
        raise FirebaseAuthConfigurationError("FIREBASE_PROJECT_ID is not configured")

    try:
        from google.oauth2 import id_token as google_id_token

        decoded = google_id_token.verify_firebase_token(
            token,
            _public_certificate_request(),
            audience=project_id,
            clock_skew_in_seconds=_MAX_CLOCK_SKEW_SECONDS,
        )
    except FirebaseAuthConfigurationError:
        raise
    except Exception as exc:
        raise FirebaseAuthTokenError("Google sign-in could not be verified") from exc

    if not isinstance(decoded, dict):
        raise FirebaseAuthTokenError("Google sign-in token payload is invalid")
    _validate_public_certificate_claims(decoded, project_id)
    return decoded


def verify_google_firebase_token(id_token):
    """Verify a Firebase ID token and require the Google sign-in provider."""
    token = str(id_token or "").strip()
    if not token or len(token) > 20_000:
        raise FirebaseAuthTokenError("A valid Google sign-in token is required")

    try:
        from firebase_admin import auth
    except ImportError:
        decoded = _verify_with_public_certificates(token)
    else:
        try:
            app = _firebase_app()
        except FirebaseAuthConfigurationError:
            # Signature verification only needs the Firebase project ID and
            # Google's public certificates. Keep service-account credentials
            # optional for login while Admin operations such as FCM remain
            # independently credentialed.
            decoded = _verify_with_public_certificates(token)
        else:
            try:
                decoded = auth.verify_id_token(token, app=app, check_revoked=False)
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
