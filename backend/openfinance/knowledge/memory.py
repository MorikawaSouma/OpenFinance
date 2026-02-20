from abc import ABC, abstractmethod


class SemanticMemoryStore(ABC):
    @abstractmethod
    def save_preference(self, key: str, value: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_preference(self, key: str) -> str | None:
        raise NotImplementedError


class EpisodicMemoryStore(ABC):
    @abstractmethod
    def append_episode(self, episode: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_episodes(self) -> list[str]:
        raise NotImplementedError


class ProjectMemoryStore(ABC):
    @abstractmethod
    def save_project_note(self, note: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_project_notes(self) -> list[str]:
        raise NotImplementedError


class InMemorySemanticMemory(SemanticMemoryStore):
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def save_preference(self, key: str, value: str) -> None:
        self._data[key] = value

    def get_preference(self, key: str) -> str | None:
        return self._data.get(key)


class InMemoryEpisodicMemory(EpisodicMemoryStore):
    def __init__(self) -> None:
        self._episodes: list[str] = []

    def append_episode(self, episode: str) -> None:
        self._episodes.append(episode)

    def list_episodes(self) -> list[str]:
        return list(self._episodes)


class InMemoryProjectMemory(ProjectMemoryStore):
    def __init__(self) -> None:
        self._notes: list[str] = []

    def save_project_note(self, note: str) -> None:
        self._notes.append(note)

    def list_project_notes(self) -> list[str]:
        return list(self._notes)
