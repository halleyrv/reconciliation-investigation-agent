"""Every error the API returns is a Problem Details body (RFC 9457) with no exception text."""

import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


def problem(status: int, detail: str, **extra: object) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        **extra,
    }
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type="application/problem+json"
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    # an adapter adds members to the problem by raising a mapping as its detail
    if isinstance(exc.detail, Mapping):
        return problem(exc.status_code, **exc.detail)
    return problem(exc.status_code, str(exc.detail))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return problem(422, "the request is not valid", errors=errors)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unexpected error on %s %s", request.method, request.url.path, exc_info=exc)
    return problem(500, "the server could not complete the request")


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
