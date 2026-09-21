"""Message schema: version tag, sender identity, addressing.

Spec: "Participant identity", "Message bus".
"""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class Role(str, Enum):
    """Role tag for a message within a model prompt (system, user or assistant)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class SenderKind(str, Enum):
    PARTICIPANT = "participant"
    CHAIRMAN = "chairman"
    SUMMARIZER = "summarizer"
    CALLER = "caller"
    ORCHESTRATOR = "orchestrator"


class Identity(BaseModel):
    """Identifies a participant, the chairman or the summarizer.

    Repeated instances of the same model stay distinguishable via
    ``instance_label`` (see spec: Participant identity).
    """

    model_config = ConfigDict(frozen=True)

    kind: SenderKind
    model_name: str | None = None
    instance_label: str | None = None

    def display_name(self) -> str:
        if self.kind is SenderKind.PARTICIPANT:
            label = self.instance_label or ""
            return f"{self.model_name}{label}"
        return self.kind.value


class Addressee(BaseModel):
    """Who a message is addressed to: everyone, one participant, or the caller."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["all", "participant", "caller"]
    target: Identity | None = None


class Message(BaseModel):
    """One message on the bus.

    Every message carries a schema version tag so the bus, event log and
    resumed run state can evolve across releases without breaking a run
    recorded under an older version (see spec: Message bus).
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    id: str = Field(default_factory=lambda: str(uuid4()))
    sender: Identity
    addressee: Addressee
    iteration: int
    round: int
    role: Role = Role.ASSISTANT
    content: str
    is_private: bool = False
    stance: str | None = None
