"""Bound request bodies before multipart/form/JSON parsing, including chunked uploads."""
from fastapi.responses import JSONResponse


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = 6 * 1024 * 1024 if path == "/services/maps" else (16 * 1024 if path == "/auth/token" else 64 * 1024)
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        declared = None
        if lengths and any(k.lower() == b"transfer-encoding" for k, _ in scope.get("headers", [])):
            return await JSONResponse(status_code=400, content={"detail": "Ambiguous request length"})(scope, receive, send)
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                return await JSONResponse(status_code=400, content={"detail": "Invalid request length"})(scope, receive, send)
            if len(lengths[0]) > 12:
                return await self.reject(scope, receive, send)
            declared = int(lengths[0])
            if declared > limit:
                return await self.reject(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                return await JSONResponse(status_code=400, content={"detail": "Invalid request body"})(scope, receive, send)
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await self.reject(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if declared is not None and declared != len(body):
            return await JSONResponse(status_code=400, content={"detail": "Invalid request length"})(scope, receive, send)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)

    async def reject(self, scope, receive, send):
        await JSONResponse(status_code=413, content={"detail": "حجم درخواست بیش از حد مجاز است."})(scope, receive, send)
