from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import List, Optional, Union, Any
from pydantic import BaseModel
from fastapi import status  # To use HTTP status codes like 404, 403, etc.


# Define the custom response model
class APIResponse(BaseModel):
    login_info: Optional[dict] = None
    success: bool
    message: str
    data: Optional[Union[List, dict, str, int, float, bool]] = None  # Flexible data type
    extra_meta: Optional[dict] = None
    error: Optional[dict] = None  # Optional error details, default is None


class ResponseHandler:

    @staticmethod
    def success(
        message: str, data: Any = None, login_info: Optional[dict] = None, extra_meta: Optional[dict] = None
    ) -> JSONResponse:
        """
        Return a successful response.

        Args:
            message (str): A success message.
            data (List[dict]): Data to be returned in the response.

        Returns:
            JSONResponse: A FastAPI response object with success status.
        """
        if data is None:
            data = []
        response_data = APIResponse(
            login_info=login_info,
            success=True,
            message=message,
            data=data,
            extra_meta=extra_meta,
            error={},
        )
        return JSONResponse(
            content=jsonable_encoder(response_data), status_code=status.HTTP_200_OK
        )

    @staticmethod
    def error(message: str, error_details: dict = None) -> JSONResponse:
        """
        Return an error response.

        Args:
            message (str): Error message to be returned.
            error_details (dict): Additional details about the error.

        Returns:
            JSONResponse: A FastAPI response object with error status.
        """
        if error_details is None:
            error_details = {}
        response_data = APIResponse(
            success=False,
            message=message,
            data=[],
            error=error_details,
        )
        return JSONResponse(
            content=jsonable_encoder(response_data), status_code=status.HTTP_400_BAD_REQUEST
        )

    @staticmethod
    def raise_http_error(
        message: str,
        error_details: dict = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        """
        Raise an HTTP error (for non-200 status codes).

        Args:
            message (str): Error message to be returned.
            error_details (dict): Additional details about the error.

        Raises:
            HTTPException: Raises a custom HTTPException with a detailed error message.
        """
        if error_details is None:
            error_details = {}
        response_data = APIResponse(
            success=False,
            message=message,
            data=[],
            error=error_details,
        )
        raise HTTPException(status_code=status_code, detail=response_data.dict())

    @staticmethod
    def not_found(message: str, error_details: dict = None) -> JSONResponse:
        """
        Handle a 'Not Found' error (HTTP 404).

        Args:
            message (str): Error message to be returned.
            error_details (dict): Additional details about the error.

        Returns:
            JSONResponse: A FastAPI response object with status 404 (Not Found).
        """
        if error_details is None:
            error_details = {}
        response_data = APIResponse(
            success=False,
            message=message,
            data=[],
            error=error_details,
        )
        return JSONResponse(
            content=jsonable_encoder(response_data), status_code=status.HTTP_404_NOT_FOUND
        )

    @staticmethod
    def forbidden(message: str, error_details: dict = None) -> JSONResponse:
        """
        Handle a 'Forbidden' error (HTTP 403).

        Args:
            message (str): Error message to be returned.
            error_details (dict): Additional details about the error.

        Returns:
            JSONResponse: A FastAPI response object with status 403 (Forbidden).
        """
        if error_details is None:
            error_details = {}
        response_data = APIResponse(
            success=False,
            message=message,
            data=[],
            error=error_details,
        )
        return JSONResponse(
            content=jsonable_encoder(response_data), status_code=status.HTTP_403_FORBIDDEN
        )

    @staticmethod
    def handle_exception(request: Request, exc: Exception) -> JSONResponse:
        # Check for validation errors
        if isinstance(exc, RequestValidationError):
            # Extract details from the validation exception
            # print('==erors',exc.errors())

            formatError = {}
            input_captured = False

            for error in exc.errors():
                # print(error)
                # Capture input once from the first error that has it
                if not input_captured and "input" in error:
                    formatError["input"] = error["input"]
                    input_captured = True

                if len(error["loc"]) < 2:
                    if "body" not in formatError:
                         formatError["body"] = {}
                    formatError["body"]["__root__"] = {"type": error.get("type"), "msg": error.get("msg")}
                    continue

                # Handle potentially nested locations by joining them or using the last part
                # Preserving existing logic style which seems to assume (location_type, field_name)
                # but making it slightly more robust to just use the last element as field name
                # and the first element as the key (usually 'body' or 'query')
                
                loc_root = str(error["loc"][0])
                field_name = str(error["loc"][-1])
                
                # If we want to strictly follow the previous "_, field = ..." unpacking but safe:
                # loc_root = error["loc"][0]
                # field_name = error["loc"][1] if len(error["loc"]) > 1 else "__all__"

                if loc_root not in formatError:
                    formatError[loc_root] = {}
                
                formatError[loc_root][field_name] = {
                    key: error[key] for key in error if key not in ["loc", "input", "ctx", "url"]
                }

            if not formatError:
                formatError = {}

            response_data = APIResponse(
                success=False,
                message="Validation Errors",
                #  data=None,
                error=formatError,
            )
            return JSONResponse(
                content=jsonable_encoder(response_data), status_code=status.HTTP_400_BAD_REQUEST
            )

        # Handle other exceptions as a general internal server error
        else:
            response_data = APIResponse(
                success=False,
                message="Internal Server Error",
                error={"detail": str(exc)},
            )
            return JSONResponse(content=jsonable_encoder(response_data), status_code=500)
