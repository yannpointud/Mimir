"""
Errors raised by application services for the API layer to translate.
"""

from http import HTTPStatus


class RequestRejectedError(Exception):
    """A request a service refuses, with the status and message the client sees.

    Services stay independent of FastAPI: each route turns this error into an
    HTTPException carrying the same status code and detail.
    """

    def __init__(self, status: HTTPStatus, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status)
        self.detail = detail
