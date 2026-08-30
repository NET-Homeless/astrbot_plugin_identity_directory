"""Domain errors raised by the identity directory."""

from __future__ import annotations


class DirectoryError(RuntimeError):
    """Base class for expected directory operation failures."""


class DirectoryNotFoundError(DirectoryError):
    """An account, person, or other referenced record does not exist."""


class DirectoryConflictError(DirectoryError):
    """An operation would violate an identity or lifecycle invariant."""


class DirectoryClosedError(DirectoryError):
    """The directory service has already been closed."""
