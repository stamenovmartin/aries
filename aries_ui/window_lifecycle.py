"""Completion dismissal uses observed state, never an assumed task duration."""
import time

class CompletionClose:
    def __init__(self, temporary=False, delay=45, clock=time.monotonic):
        self.pinned = not temporary
        self.delay, self.clock, self.deadline = delay, clock, None

    def pin(self, value):
        self.pinned = value
        self.deadline = None

    def update(self, state):
        # Keep failures and approval requests visible for a decision.
        if self.pinned or state != 'done':
            self.deadline = None
            return False
        now = self.clock()
        if self.deadline is None:
            self.deadline = now + self.delay
        return now >= self.deadline
