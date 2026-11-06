import logging
from time import monotonic

logger = logging.getLogger(__name__)


class RegistryUnavailable(Exception):
    pass


class RegistryBreaker:
    """Process-local breaker used from the broker's async event loop."""

    def __init__(self):
        self.failures = 0
        self.reopen_at: float | None = None
        self.probing = False
        self.generation = 0

    def acquire(self) -> int:
        if self.reopen_at is not None:
            if self.probing or monotonic() < self.reopen_at:
                raise RegistryUnavailable
            self.probing = True
        return self.generation

    def finish(self, generation: int, outcome: str) -> None:
        if generation != self.generation:
            return
        if outcome == "reachable":
            self.failures = 0
            if self.probing:
                self.generation += 1
                self.reopen_at = None
                self.probing = False
                logger.info("Registry connection recovered")
        elif outcome == "unavailable" or self.probing:
            self.failures += 1
            if self.probing or self.failures >= 5:
                self.reopen_at = monotonic() + 60
                self.probing = False
                self.generation += 1
                logger.warning("Registry circuit opened for 60 seconds")
