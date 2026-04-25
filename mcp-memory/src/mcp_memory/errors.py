class MemoryError(Exception):
    """Base application error."""


class VersionConflictError(MemoryError):
    """Raised on optimistic concurrency mismatch."""


class NotFoundError(MemoryError):
    """Raised when a record is missing."""


class InvalidRequestError(MemoryError):
    """Raised on invalid state transitions or payloads."""
