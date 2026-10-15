"""HTTP responses shared by several routes and exception handlers."""

from fastapi import status
from fastapi.responses import JSONResponse

BUDGET_EXCEEDED_MESSAGE = "Plafond quotidien de dépense IA atteint."


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
