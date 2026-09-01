from abc import ABC, abstractmethod
from enum import Enum


class ProviderEvent(Enum):
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    CONNECTED = "CONNECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TelecomProvider(ABC):

    @abstractmethod
    def initiate_call(self, call_id, phone_number):
        pass