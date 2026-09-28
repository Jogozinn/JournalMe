from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrokerConnection

TOKEN_PREFIX = "jmbrg"


@dataclass(frozen=True)
class IssuedBridgeToken:
    token: str
    prefix: str
    created_at: datetime


def issue_bridge_token(connection: BrokerConnection) -> IssuedBridgeToken:
    secret = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}.{connection.id}.{secret}"
    created_at = datetime.now(timezone.utc)
    connection.bridge_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    connection.bridge_token_prefix = token[:24]
    connection.bridge_token_created_at = created_at
    return IssuedBridgeToken(token=token, prefix=connection.bridge_token_prefix, created_at=created_at)


def revoke_bridge_token(connection: BrokerConnection) -> None:
    connection.bridge_token_hash = None
    connection.bridge_token_prefix = None
    connection.bridge_token_created_at = None


def authenticate_bridge_token(db: Session, token: str | None) -> BrokerConnection:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bridge authentication is required.")
    parts = token.split(".", 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bridge token is invalid.")
    try:
        connection_id = UUID(parts[1])
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bridge token is invalid.") from exc
    connection = db.scalar(select(BrokerConnection).where(BrokerConnection.id == connection_id))
    if connection is None or not connection.bridge_token_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bridge token is invalid or revoked.")
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, connection.bridge_token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bridge token is invalid or revoked.")
    return connection
