"""HTTP endpoints for login and logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr

from .. import auth


router = APIRouter()
bearer = HTTPBearer(auto_error=False)
SessionToken = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def token_value(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    return credentials.credentials if credentials else None


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=150)
    password: SecretStr = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(body: LoginRequest, response: Response):
    token = auth.login(body.email, body.password.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return {"session_token": token, "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(credentials: SessionToken) -> None:
    auth.logout(token_value(credentials))
