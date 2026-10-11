import time

from mcp.server.mcpserver import MCPServer

server = MCPServer("echo")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return text


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("nope")


@server.tool()
def sleep(seconds: float) -> str:
    """Sleep, to test timeouts."""
    time.sleep(seconds)
    return "woke"


if __name__ == "__main__":
    server.run()
