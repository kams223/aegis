"""Immutable delivery-order cursors for small synthetic inspection histories."""

from dataclasses import dataclass

from aegis.fusion.observation_history import ObservationHistory


@dataclass(frozen=True)
class ReplayState:
    """None is before first; visited_prefix ends at the selected occurrence.

    This is a cursor frontier, not a persistent log of clicks or acquisitions.
    Backward and reset shorten the prefix. End boundaries are no-ops.
    """

    history: ObservationHistory
    position: int | None = None

    def __post_init__(self):
        if not isinstance(self.history, ObservationHistory):
            raise TypeError("history must be ObservationHistory")
        if self.position is not None:
            self._check_position(self.position)

    def _check_position(self, position):
        if type(position) is not int:
            raise TypeError("position must be an integer")
        if not 0 <= position < self.total_count:
            raise IndexError("position must identify an existing history occurrence")

    @property
    def total_count(self):
        return len(self.history.records)

    @property
    def current(self):
        return None if self.position is None else self.history.records[self.position]

    @property
    def visited_prefix(self):
        return self.history.records[:0 if self.position is None else self.position + 1]

    @property
    def previous_occurrences(self):
        return self.history.records[:0 if self.position is None else self.position]

    @property
    def future_occurrences(self):
        return self.history.records[0 if self.position is None else self.position + 1:]

    def step_forward(self):
        next_position = 0 if self.position is None else self.position + 1
        return self if next_position >= self.total_count else ReplayState(self.history, next_position)

    def step_backward(self):
        if self.position is None:
            return self
        return ReplayState(self.history, None if self.position == 0 else self.position - 1)

    def jump(self, position):
        self._check_position(position)
        return self if position == self.position else ReplayState(self.history, position)

    def reset(self):
        return self if self.position is None else ReplayState(self.history)
