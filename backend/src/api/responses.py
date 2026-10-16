"""HTTP responses shared by several routes and exception handlers."""

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

from src.services.errors import RequestRejectedError

BUDGET_EXCEEDED_MESSAGE = "Plafond quotidien de dépense IA atteint."


def rejection_to_http(error: RequestRejectedError) -> HTTPException:
    """HTTPException with the status code and message of a service rejection."""
    return HTTPException(status_code=error.status_code, detail=error.detail)


def budget_exceeded_response() -> JSONResponse:
    """429 answered when the daily AI budget is exhausted.

    Returned as a Response rather than raised as an HTTPException: the global
    HTTPException handler would rewrite the body to the generic "HTTP_429"
    shape and drop the distinct ``budget_exceeded`` error code.
    """
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error_code": "budget_exceeded", "error_message": BUDGET_EXCEEDED_MESSAGE},
    )
