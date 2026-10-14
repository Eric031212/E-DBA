"""Domain errors. The web and API layers translate them into flashes / HTTP errors."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class Conflict(DomainError):
    status_code = 409


class PaymentRequired(DomainError):
    status_code = 402


class UpstreamError(DomainError):
    """The organization's own API (or the bank) failed or returned something unusable."""

    status_code = 502
