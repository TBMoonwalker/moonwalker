"""Runtime state helpers for Autopilot mode and threshold deduplication."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutopilotRuntimeState:
    """Process-local runtime state shared by Autopilot collaborators."""

    last_threshold_percent: float | None = None
    last_mode: str | None = None

    def update_mode(self, autopilot_mode: str) -> bool:
        """Record a mode change and return whether it changed."""
        if autopilot_mode == self.last_mode:
            return False
        self.last_mode = autopilot_mode
        return True

    def update_threshold_percent(self, threshold_percent: float) -> bool:
        """Record a threshold change and return whether it changed."""
        if threshold_percent == self.last_threshold_percent:
            return False
        self.last_threshold_percent = threshold_percent
        return True


_shared_runtime_state = AutopilotRuntimeState()


def get_shared_autopilot_runtime_state() -> AutopilotRuntimeState:
    """Return the shared process-local Autopilot runtime state."""
    return _shared_runtime_state
