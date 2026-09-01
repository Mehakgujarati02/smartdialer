from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentStatus(Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DIALING = "DIALING"
    CONNECTED = "CONNECTED"
    WRAP_UP = "WRAP_UP"
    PAUSED = "PAUSED"


class BorrowerStatus(Enum):
    WAITING = "WAITING"
    RESERVED = "RESERVED"
    CALLED = "CALLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CallStatus(Enum):
    QUEUED = "QUEUED"
    RESERVED = "RESERVED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    CONNECTED = "CONNECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    # A human answered but no agent was free to take the call. Distinct
    # from FAILED (provider/technical failure) -- this is the specific
    # compliance-risk outcome the assignment calls out: a live person on
    # the line with nobody to talk to them.
    ABANDONED = "ABANDONED"


@dataclass
class Agent:
    id: str
    name: str
    status: AgentStatus = AgentStatus.OFFLINE


@dataclass
class Borrower:
    id: str
    name: str
    phone_number: str
    priority: int = 0
    status: BorrowerStatus = BorrowerStatus.WAITING


@dataclass
class Call:
    id: str
    borrower_id: str
    # None until an agent is actually bound to this call. Progressive
    # dialing binds an agent at creation time (never None). Predictive
    # dialing may create a call with no agent yet and only bind one when
    # the call is actually ANSWERED -- see CallAllocator.try_bind_agent().
    agent_id: Optional[str] = None
    status: CallStatus = CallStatus.QUEUED