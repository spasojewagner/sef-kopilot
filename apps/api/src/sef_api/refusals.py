"""A request that the API's models refuse, answered without what it held.

FastAPI answers 422 with each error's ``input``: the value refused, or, for a field that is
missing, the whole object around it. That would send back a password too short, or a key sent
under the wrong name, in the answer, where a proxy, a browser's tools or a client's log keep it.
The answer here says where and why, each error's ``type``, ``loc``, ``msg`` and the limits in
``ctx``, and never what was sent.
"""

from __future__ import annotations

from typing import cast

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

__all__ = ["answer_refused"]


async def answer_refused(_request: Request, refused: Exception) -> JSONResponse:
    """422 with what was wrong with the request, without the values it held."""
    errors = [
        {name: value for name, value in error.items() if name != "input"}
        for error in cast(RequestValidationError, refused).errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )
