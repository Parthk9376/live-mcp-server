import hashlib
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool

app = FastAPI()
server = Server("live-challenge-server")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="solve_challenge",
            description="Solve the current exam challenge using its HTTP header.",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]):
    if name != "solve_challenge":
        raise ValueError("Unknown tool")

    challenge = current_challenge.get()
    if not challenge:
        raise ValueError("Missing X-Exam-Challenge header")

    email = "24f2001122@ds.study.iitm.ac.in".strip().lower()
    result = hashlib.sha256(f"{challenge}:{email}".encode()).hexdigest()[:16]

    return [TextContent(type="text", text=result)]


from contextvars import ContextVar

current_challenge = ContextVar("current_challenge", default=None)


session_manager = StreamableHTTPSessionManager(
    app=server,
    event_store=None,
    json_response=True,
    stateless=True,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def mcp_endpoint(request: Request):
    challenge = request.headers.get("X-Exam-Challenge")
    token = current_challenge.set(challenge)

    try:
        async def receive():
            body = await request.body()
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        async def send(message):
            pass

        from starlette.responses import StreamingResponse

        messages = []

        async def real_send(message):
            messages.append(message)

        await session_manager.handle_request(
            request.scope,
            receive,
            real_send,
        )

        headers = {}
        status = 200
        body = b""

        for message in messages:
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = dict(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body += message.get("body", b"")

        return Response(
            content=body,
            status_code=status,
            headers={
                k.decode("latin1"): v.decode("latin1")
                for k, v in headers.items()
            },
        )
    finally:
        current_challenge.reset(token)


@app.on_event("startup")
async def startup():
    await session_manager.run()


@app.on_event("shutdown")
async def shutdown():
    await session_manager.close()
