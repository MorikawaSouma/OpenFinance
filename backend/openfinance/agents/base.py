from abc import ABC, abstractmethod

from openfinance.agents.schemas import AgentOutput, AgentTaskInput


class BaseAgent(ABC):
    name: str = "base"
    model: str = "stub-model"

    @abstractmethod
    def run(self, task: AgentTaskInput) -> AgentOutput:
        raise NotImplementedError
