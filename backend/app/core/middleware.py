"""
Middleware Setup for FastAPI Application

This module defines and registers custom and standard middleware components
for the FastAPI web application. Middleware here is responsible for handling
cross-origin resource sharing (CORS) policies and URL path normalization.

Key Responsibilities:
---------------------
- Define a custom middleware (`NormalizePathMiddleware`) to clean URL paths
  by collapsing multiple consecutive slashes into single slashes.
- Register middleware components, including CORS handling and path normalization,
  on the FastAPI app instance to ensure requests are properly processed.

Main Components:
----------------
1. **NormalizePathMiddleware (Starlette BaseHTTPMiddleware subclass)**:
   Custom middleware to intercept incoming requests and normalize URL paths by 
   replacing occurrences of multiple consecutive slashes (`//`) with a single slash (`/`).
   This helps avoid routing issues caused by malformed URLs.

2. **register_middleware (function)**:
   Function to attach middleware components to a FastAPI app instance. It applies:
   - `CORSMiddleware` configured with allowed origins and credentials based on the
     frontend URL from configuration.
   - `NormalizePathMiddleware` for URL path cleanup.

Note:
-----
- `FRONTEND` is imported from app configuration and determines the allowed CORS origin.
- This module expects to be called during app initialization, before the app starts serving requests.

Typical Use:
------------
Call `register_middleware(app)` passing a FastAPI app instance to enable CORS and
automatic path normalization for all incoming requests.
"""
from typing import Callable, Awaitable
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import FRONTEND

class NormalizePathMiddleware(BaseHTTPMiddleware):
    """
    Middleware to normalize incoming HTTP request paths by replacing any double slashes "//"
    with a single slash "/", ensuring consistent URL path formatting across the application.
    """
    async def dispatch(
        self, 
        request: Request, 
        call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Intercept incoming HTTP requests, normalize the URL path by collapsing
        consecutive slashes, then forward the modified request to the next middleware
        or route handler in the ASGI stack.

        Args:
            request (Request): The incoming HTTP request.
            call_next (Callable[[Request], Awaitable[Response]]): Function that processes
                the request by passing it to the next ASGI middleware or route handler,
                returning an awaitable Response.

        Returns:
            Response: The HTTP response returned after processing the normalized request.
        """
        scope = request.scope
        path = scope["path"]
        normalized_path = path.replace("//", "/")
        if normalized_path != path:
            scope["path"] = normalized_path
        response = await call_next(Request(scope, receive=request.receive))
        return response

def register_middleware(app: FastAPI)-> None:
    """
    Register middleware on the FastAPI application instance.

    Adds middleware components in the following order:
    1. CORSMiddleware configured with allowed origins, credentials, methods, and headers.
    2. NormalizePathMiddleware to clean URL paths.

    Args:
        app (FastAPI): The FastAPI application instance to register middleware on.

    Returns:
        None
    """
    app.add_middleware(CORSMiddleware,
        allow_origins=[FRONTEND],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(NormalizePathMiddleware)