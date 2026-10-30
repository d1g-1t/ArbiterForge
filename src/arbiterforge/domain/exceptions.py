from __future__ import annotations


class DomainError(Exception):
    pass


class ConcurrencyError(DomainError):
    def __init__(self, aggregate_id: str, expected: int, actual: int | None) -> None:
        self.aggregate_id = aggregate_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Concurrency conflict on {aggregate_id}: expected version {expected}, actual {actual}"
        )


class InvalidTransitionError(DomainError):
    def __init__(self, current: str, event_type: str, message: str | None = None) -> None:
        self.current = current
        self.event_type = event_type
        super().__init__(
            message or f"Invalid transition: cannot apply {event_type} from status {current}"
        )


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} not found: {entity_id}")


class AuthorizationError(DomainError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message)


class ValidationError(DomainError):
    def __init__(self, message: str, *, basis: tuple[str, ...] = ()) -> None:
        self.basis = basis
        super().__init__(message)


class CalendarCoverageError(DomainError):
    def __init__(self, year: int) -> None:
        self.year = year
        super().__init__(f"Production calendar for {year} is not loaded")
