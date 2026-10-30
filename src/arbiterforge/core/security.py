from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import pyseto
from pydantic import BaseModel

from arbiterforge.core.config import get_settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


class Role(StrEnum):
    ADMIN = "ADMIN"
    CASE_MANAGER = "CASE_MANAGER"
    COUNSEL = "COUNSEL"
    ARBITRATOR_READONLY = "ARBITRATOR_READONLY"
    AUDITOR_READONLY = "AUDITOR_READONLY"


class Permissions:
    ORG_MANAGE = "org:manage"
    CASE_READ = "case:read"
    CASE_WRITE = "case:write"
    TRIBUNAL_MANAGE = "tribunal:manage"
    SUBMISSION_FILE = "submission:file"
    AWARD_ISSUE = "award:issue"
    PROJECTION_REBUILD = "projection:rebuild"
    AUDIT_READ = "audit:read"
    AI_SUGGEST = "ai:suggest"
    PO_ACCEPT = "po:accept"
    ADMIN = "admin"


_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.ADMIN: frozenset(
        {
            Permissions.ORG_MANAGE,
            Permissions.CASE_READ,
            Permissions.CASE_WRITE,
            Permissions.TRIBUNAL_MANAGE,
            Permissions.SUBMISSION_FILE,
            Permissions.AWARD_ISSUE,
            Permissions.PROJECTION_REBUILD,
            Permissions.AUDIT_READ,
            Permissions.AI_SUGGEST,
            Permissions.PO_ACCEPT,
            Permissions.ADMIN,
        }
    ),
    Role.CASE_MANAGER: frozenset(
        {
            Permissions.CASE_READ,
            Permissions.CASE_WRITE,
            Permissions.TRIBUNAL_MANAGE,
            Permissions.SUBMISSION_FILE,
            Permissions.AI_SUGGEST,
            Permissions.PO_ACCEPT,
            Permissions.AUDIT_READ,
        }
    ),
    Role.COUNSEL: frozenset(
        {
            Permissions.CASE_READ,
            Permissions.CASE_WRITE,
            Permissions.SUBMISSION_FILE,
            Permissions.AI_SUGGEST,
            Permissions.AUDIT_READ,
        }
    ),
    Role.ARBITRATOR_READONLY: frozenset({Permissions.CASE_READ, Permissions.AUDIT_READ}),
    Role.AUDITOR_READONLY: frozenset({Permissions.CASE_READ, Permissions.AUDIT_READ}),
}


def has_permission(role: str, permission: str) -> bool:
    return permission in _ROLE_PERMISSIONS.get(role, frozenset())


class TokenPayload(BaseModel):
    sub: str
    email: str
    role: str
    org_id: str
    exp: datetime
    iat: datetime


class InvalidTokenError(Exception):
    pass


def _key() -> pyseto.Key:
    secret = get_settings().token_secret.get_secret_value().encode()
    return pyseto.Key.new(version=4, purpose="local", key=hashlib.sha256(secret).digest())


def create_access_token(payload: dict[str, Any], *, ttl_minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    ttl = ttl_minutes if ttl_minutes is not None else get_settings().access_token_ttl_minutes
    data = {**payload, "iat": now.isoformat(), "exp": (now + timedelta(minutes=ttl)).isoformat()}
    return pyseto.encode(_key(), data).decode()


def decode_access_token(token: str) -> TokenPayload:
    try:
        decoded = pyseto.decode(_key(), token)
    except Exception as exc:
        raise InvalidTokenError("Invalid token") from exc
    payload = decoded.payload
    if isinstance(payload, bytes):
        payload = json.loads(payload)
    data = TokenPayload.model_validate(payload)
    if datetime.now(UTC) >= data.exp:
        raise InvalidTokenError("Token expired")
    return data
