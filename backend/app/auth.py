from collections.abc import Callable
from typing import Annotated, Protocol
from uuid import UUID

try:  # Local mode must remain usable before optional cloud dependencies are installed.
    import jwt
except ImportError:  # pragma: no cover - exercised only in an incomplete deployment
    jwt = None  # type: ignore[assignment]
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuthIdentity, User


class IdentityProvider(Protocol):
    """Future hosted auth adapts here; routes continue to depend on current user only."""

    def current_user(self, db: Session) -> User: ...


bearer = HTTPBearer(auto_error=False)


class SupabaseJwtVerifier:
    """Verify Supabase access tokens against its published signing keys."""

    def __init__(self, url: str, audience: str) -> None:
        if jwt is None:
            raise RuntimeError("PyJWT[crypto] is required for JOURNALME_DATA_PROVIDER=supabase.")
        self.issuer = f"{url.rstrip('/')}/auth/v1"
        self.audience = audience
        self.jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json")

    def __call__(self, token: str) -> dict[str, object]:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=self.audience,
            issuer=self.issuer,
        )
        return dict(claims)


class LocalIdentityProvider:
    def current_user(self, db: Session) -> User:
        settings = get_settings()
        user = db.scalar(select(User).where(User.email == settings.local_user_email))
        if user is None:
            user = User(email=settings.local_user_email, display_name=settings.local_user_name)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user


class SupabaseIdentityProvider:
    """Map a verified Supabase subject to an explicitly linked JournalMe user."""

    def __init__(self, verifier: Callable[[str], dict[str, object]] | None = None) -> None:
        settings = get_settings()
        self.verifier = verifier or SupabaseJwtVerifier(
            settings.supabase_url or "", settings.supabase_jwt_audience
        )

    def current_user(self, db: Session, token: str | None) -> User:
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is required.")
        try:
            claims = self.verifier(token)
        except Exception as exc:
            if jwt is not None and isinstance(exc, jwt.ExpiredSignatureError):
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, "Authentication token has expired."
                ) from exc
            if jwt is not None and isinstance(exc, jwt.InvalidTokenError):
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, "Authentication token is invalid."
                ) from exc
            # Do not turn a JWKS/network failure into an unauthenticated local user.
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Authentication token could not be verified."
            ) from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Authentication token is missing its subject."
            )
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "supabase", AuthIdentity.subject == subject
            )
        )
        if identity is None:
            email = claims.get("email")
            if not isinstance(email, str) or not email.strip():
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "The authenticated Supabase account is missing an email address.",
                )
            normalized_email = email.strip().lower()
            user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
            if user is None:
                metadata = claims.get("user_metadata")
                display_name = None
                if isinstance(metadata, dict):
                    candidate = metadata.get("display_name") or metadata.get("full_name") or metadata.get("name")
                    if isinstance(candidate, str) and candidate.strip():
                        display_name = candidate.strip()[:120]
                user = User(
                    email=normalized_email,
                    display_name=display_name or normalized_email.split("@", 1)[0][:120] or "Trader",
                )
                db.add(user)
                db.flush()
            identity = AuthIdentity(
                user_id=user.id, provider="supabase", subject=subject
            )
            db.add(identity)
            db.commit()
            db.refresh(user)
            return user
        user = db.get(User, identity.user_id)
        if user is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "The linked JournalMe user no longer exists."
            )
        return user


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    """Authoritative current-user dependency for local and verified hosted modes."""
    if get_settings().data_provider == "local":
        return LocalIdentityProvider().current_user(db)
    token = credentials.credentials if credentials else None
    return SupabaseIdentityProvider().current_user(db, token)


def current_user_id(user: Annotated[User, Depends(get_current_user)]) -> UUID:
    """Authoritative user-id dependency for future provider-neutral service boundaries."""
    return user.id
