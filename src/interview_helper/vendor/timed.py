"""Minimal timed objects adapted from WhisperLiveKit (Apache-2.0)."""
from dataclasses import dataclass, replace

@dataclass
class ASRToken:
    start: float
    end: float
    text: str
    probability: float | None = None

    def with_offset(self, offset):
        return replace(self, start=self.start + offset, end=self.end + offset)

@dataclass
class Transcript:
    start: float | None
    end: float | None
    text: str

Sentence = Transcript
