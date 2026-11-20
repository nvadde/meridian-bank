"""FastAPI entry point for Meridian Trust Bank."""

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.authorization import AuthError, audit_rejected_request
from backend.app.chat import chat_api
from backend.app.database import get_connection
from backend.app.mcp import accounts_mcp, service_mcp, transactions_mcp
from backend.app.observability import api as observability_api
from backend.app.routes import account_routes, admin_routes, auth_routes


mcp_servers = {
    "/mcp/accounts": accounts_mcp.server,
    "/mcp/transactions": transactions_mcp.server,
    "/mcp/service": service_mcp.server,
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with AsyncExitStack() as stack:
        for server in mcp_servers.values():
            await stack.enter_async_context(server.session_manager.run())
        yield


app = FastAPI(title="Meridian Trust Bank", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://meridian-bank.vercel.app", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_routes.router)
app.include_router(account_routes.router)
app.include_router(admin_routes.router)
app.include_router(chat_api.router)
app.include_router(observability_api.router)
for path, server in mcp_servers.items():
    app.mount(path, server.streamable_http_app())


@app.get("/health")
def health():
    try:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM DUAL")
            if cursor.fetchone() == (1,):
                return {"status": "ok", "db": "connected"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error"})
    return JSONResponse(status_code=503, content={"status": "error"})


@app.middleware("http")
async def disable_response_caching(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AuthError)
async def access_error(_request: Request, error: AuthError):
    headers = {"WWW-Authenticate": "Bearer"} if str(error) == "INVALID_SESSION" else None
    return JSONResponse(status_code=error.status, content={"detail": error.detail}, headers=headers)


async def audit_rejection(request: Request, reason: str):
    credentials = await auth_routes.bearer(request)
    await run_in_threadpool(audit_rejected_request, auth_routes.token_value(credentials), reason)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, _error: RequestValidationError):
    # Validation errors can contain the raw login body or field values.
    await audit_rejection(request, "INVALID_REQUEST")
    return JSONResponse(status_code=422, content={"detail": {"code": "INVALID_REQUEST"}})


@app.exception_handler(StarletteHTTPException)
async def rejected_request(request: Request, error: StarletteHTTPException):
    if error.status_code in (404, 405):
        await audit_rejection(request, "METHOD_NOT_ALLOWED" if error.status_code == 405 else "NOT_FOUND")
    return await http_exception_handler(request, error)
