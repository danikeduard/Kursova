import time
from dataclasses import dataclass, field


LEVEL_START_K = {"beginner": 0.15, "intermediate": 0.5, "advanced": 0.85}


@dataclass
class LearnerState:
    k: float = 0.3  
    errors: int = 0 
    avg_response_time: float = 1.0
    last_time: float | None = field(default=None, repr=False)

    @classmethod
    def from_level(cls, level: str) -> "LearnerState":
        return cls(k=LEVEL_START_K.get(level, 0.3))

    def update(self, user_input: str) -> str:
        if len(user_input.split()) < 3:
            self.errors += 1

        self.k = max(0.0, min(1.0, self.k + 0.02 - self.errors * 0.001))

        now = time.time()
        if self.last_time:
            self.avg_response_time = (self.avg_response_time + now - self.last_time) / 2
        self.last_time = now

        return self.level

    @property
    def level(self) -> str:
        if self.k < 0.3:
            return "beginner"
        if self.k < 0.7:
            return "intermediate"
        return "advanced"
