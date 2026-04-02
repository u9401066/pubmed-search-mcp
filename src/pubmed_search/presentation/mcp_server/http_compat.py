"""HTTP compatibility helpers for MCP server launchers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


def wrap_copilot_compatibility(app: ASGIApp) -> ASGIApp:
    """Wrap an ASGI app with Copilot Studio HTTP response compatibility."""
    return CopilotStudioCompatibilityMiddleware(app)


class CopilotStudioCompatibilityMiddleware:
    """Normalize 202 Accepted responses for Copilot Studio HTTP clients."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        original_status = 200
        converted = False

        async def send_wrapper(message: Message) -> None:
            nonlocal original_status, converted

            if message["type"] == "http.response.start":
                original_status = message.get("status", 200)

                if original_status == 202:
                    converted = True
                    message = dict(message)
                    message["status"] = 200

                    headers = list(message.get("headers", []))
                    headers = [(key, value) for key, value in headers if key.lower() != b"content-length"]
                    headers.append((b"content-length", b"2"))

                    if not any(key.lower() == b"content-type" for key, _ in headers):
                        headers.append((b"content-type", b"application/json"))

                    message["headers"] = headers

            elif message["type"] == "http.response.body" and converted:
                message = dict(message)
                message["body"] = b"{}"
                message["more_body"] = False

            await send(message)

        await self.app(scope, receive, send_wrapper)
