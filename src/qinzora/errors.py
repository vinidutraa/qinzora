"""Application failures independent of any HTTP framework.

Transport adapters translate these failures into their own response format.
Keep messages free of credentials and request payloads.
"""


class ApplicationError(Exception):
    """A rejected application operation, with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require[T](value: T | None, message: str = "Not found") -> T:
    if value is None:
        raise ApplicationError("not_found", message)
    return value
