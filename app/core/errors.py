from typing import Any, Dict, Optional


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        errors: Optional[Any] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.errors = errors
        self.payload = payload or {}
        super().__init__(message)
