class MCPError(Exception):
    def __init__(self, message: str, code: int | None = None):
        self.code = code
        super().__init__(message)


class MCPTimeoutError(MCPError):
    pass


class MCPConnectionError(MCPError):
    pass


class MCPToolNotFoundError(MCPError):
    pass


class MCPToolExecutionError(MCPError):
    pass
