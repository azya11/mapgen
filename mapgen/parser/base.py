from __future__ import annotations

import abc

from ..config import Config
from ..spec import SceneSpec


class Parser(abc.ABC):
    """Turns a free-text prompt into a validated SceneSpec."""

    def __init__(self, config: Config):
        self.config = config

    @abc.abstractmethod
    def parse(self, prompt: str) -> SceneSpec:  # pragma: no cover - interface
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
