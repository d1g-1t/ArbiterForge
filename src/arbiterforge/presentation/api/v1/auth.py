from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from arbiterforge.core.security import create_access_token, verify_password
from arbiterforge.infrastructure.db.models import UserModel
from arbiterforge.presentation.deps import DbSession
from arbiterforge.presentation.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: DbSession) -> TokenResponse:
    result = await session.execute(select(UserModel).where(UserModel.email == body.email))
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.hashed_password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = create_access_token(
        {"sub": user.id, "email": user.email, "role": user.role, "org_id": user.org_id}
    )
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout() -> dict[str, str]:
    return {"status": "logged_out"}
