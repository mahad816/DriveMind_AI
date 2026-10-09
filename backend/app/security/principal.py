"""Immutable identities owned by the application, never parsed from tool arguments."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.db.enums import ApplicationSessionKind


@dataclass(frozen=True)
class VerifiedGoogleIdentity:
    """Trusted attestation from a future Google verifier, NOT a verifier itself.

    Construct only after server-side Google identity verification. No request schema
    or public issuance endpoint accepts this type. Subject lookup preserves User UUIDs.
    """

    subject: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.subject, str)
            or not self.subject.isascii()
            or not 1 <= len(self.subject) <= 255
            or self.subject.strip() != self.subject
            or any(char.isspace() for char in self.subject)
            or self.subject.startswith("demo:")
        ):
            raise ValueError("Invalid verified Google subject")


@dataclass(frozen=True)
class ConversationOwner:
    kind: Literal["USER", "APPLICATION_SESSION"]
    id: UUID

    def __post_init__(self) -> None:
        if self.kind not in ("USER", "APPLICATION_SESSION") or not isinstance(self.id, UUID):
            raise ValueError("Invalid conversation owner")


@dataclass(frozen=True)
class ApplicationPrincipal:
    session_id: UUID
    kind: ApplicationSessionKind
    authenticated_user_id: UUID | None
    conversation_owner: ConversationOwner
    corpus_user_id: UUID
    demo_mode: bool

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, UUID) or not isinstance(self.corpus_user_id, UUID):
            raise ValueError("Invalid principal identity")
        if not isinstance(self.kind, ApplicationSessionKind) or not isinstance(
            self.demo_mode, bool
        ):
            raise ValueError("Invalid principal realm")
        expected = (
            ConversationOwner("APPLICATION_SESSION", self.session_id)
            if self.demo_mode
            else ConversationOwner("USER", self.corpus_user_id)
        )
        if (
            self.conversation_owner != expected
            or (
                self.demo_mode
                and (
                    self.kind != ApplicationSessionKind.DEMO_VISITOR
                    or self.authenticated_user_id is not None
                )
            )
            or (
                not self.demo_mode
                and (
                    self.kind != ApplicationSessionKind.GOOGLE_ACCOUNT
                    or self.authenticated_user_id != self.corpus_user_id
                )
            )
        ):
            raise ValueError("Inconsistent principal ownership")
