# import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
import time
from datetime import datetime


from app.core.utils import get_device_type
from app.core.logger import create_logger



logger = create_logger('system')


class LoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        user_agent = request.headers.get("user-agent", "unknown")
        client_ip = request.client.host if request.client else "unknown"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device_type = get_device_type(user_agent)
        
        logger.info(f"[{timestamp}] Incoming request: {request.method} {request.url} | IP: {client_ip} | User-Agent: {user_agent} |  Device: {device_type}")
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"[{timestamp}] Completed response: {response.status_code} in {process_time:.2f} seconds")
        return response