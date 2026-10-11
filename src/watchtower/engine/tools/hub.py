from __future__ import annotations

import asyncio
import fnmatch
import os
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from watchtower.engine.governor.audit import AuditLog

MAX_TEXT = 20_000


@dataclass(frozen=True)
class ServerSpec:
    command: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str


class ToolDenied(PermissionError):
    pass


class ToolError(Exception):
    pass


class ToolHub:
    """Calls tools on MCP stdio servers. Default-deny: a role may only call tools its policy
    lists (fnmatch patterns over "<server>.<tool>"). Argument values are never audited."""

    def __init__(self, audit: AuditLog, servers: dict[str, ServerSpec], policy: dict[str, list[str]],
                 timeout: float = 30.0):
        self._audit = audit
        self._servers = servers
        self._policy = policy
        self._timeout = timeout

    def allowed(self, role: str, server: str, tool: str) -> bool:
        name = f"{server}.{tool}"
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self._policy.get(role, []))

    def list_tools(self, server: str) -> list[str]:
        spec = self._spec(server)
        try:
            return asyncio.run(self._with_session(spec, lambda s: s.list_tools()))
        except Exception as e:
            raise ToolError(f"{server}: list_tools failed ({type(e).__name__})") from e

    def call(self, role: str, job_id: str | None, server: str, tool: str, args: dict) -> ToolResult:
        spec = self._spec(server)
        meta = {"role": role, "server": server, "tool": tool}
        if not self.allowed(role, server, tool):
            self._audit.append("tool_hub", "tool_denied", meta, job_id)
            raise ToolDenied(f"role {role!r} may not call {server}.{tool}")
        self._audit.append("tool_hub", "tool_call", {**meta, "arg_keys": sorted(args)}, job_id)
        try:
            res = asyncio.run(self._with_session(spec, lambda s: s.call_tool(tool, args)))
        except Exception as e:
            self._audit.append("tool_hub", "tool_error", {**meta, "error": type(e).__name__}, job_id)
            raise ToolError(f"{server}.{tool} failed ({type(e).__name__})") from e
        if not isinstance(res, CallToolResult):
            raise ToolError(f"{server}.{tool} returned an unsupported result type")
        text = "\n".join(c.text for c in res.content if getattr(c, "text", None) is not None)[:MAX_TEXT]
        result = ToolResult(not res.is_error, text)
        self._audit.append("tool_hub", "tool_result", {**meta, "ok": result.ok}, job_id)
        return result

    def _spec(self, server: str) -> ServerSpec:
        if server not in self._servers:
            raise ToolError(f"unknown tool server {server!r}")
        return self._servers[server]

    async def _with_session(self, spec: ServerSpec, action):
        params = StdioServerParameters(command=spec.command, args=list(spec.args))
        with open(os.devnull, "w") as errlog:
            async with asyncio.timeout(self._timeout):
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        out = await action(session)
        if hasattr(out, "tools"):
            return [t.name for t in out.tools]
        return out
