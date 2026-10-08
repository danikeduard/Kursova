from dataclasses import dataclass, field

from .adaptive import LearnerState


@dataclass
class Conversation:
    history: list[dict] = field(default_factory=list)
    state: LearnerState = field(default_factory=LearnerState)


class SessionStore:


    def __init__(self):
        self._data: dict[str, Conversation] = {}

    def get(self, sid: str) -> Conversation:
        return self._data.setdefault(sid, Conversation())

    def reset(self, sid: str, level: str = "beginner") -> Conversation:
        conv = Conversation(state=LearnerState.from_level(level))
        self._data[sid] = conv
        return conv
