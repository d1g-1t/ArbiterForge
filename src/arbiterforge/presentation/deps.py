from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from arbiterforge.core.config import Settings
from arbiterforge.core.security import InvalidTokenError, decode_access_token, has_permission
from arbiterforge.infrastructure.db.models import UserModel

_bearer = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: DbSession,
) -> UserModel:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    user = await session.get(UserModel, payload.sub)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


CurrentUser = Annotated[UserModel, Depends(get_current_user)]


def require_permission(permission: str) -> Callable[[UserModel], Awaitable[UserModel]]:
    async def _dep(user: CurrentUser) -> UserModel:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return _dep


def parse_if_match(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    raw = if_match.strip().removeprefix("W/").strip('"')
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "If-Match must be integer version"
        ) from None


IfMatch = Annotated[str | None, Header(alias="If-Match")]
