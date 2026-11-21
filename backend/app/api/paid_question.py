"""HTTP face of the paid-question quota (M0-SEC ticket 06).

The quota logic lives in ``app.services.paid_question_quota``; this module only provides the
request-scoped dependency and turns its refusals into responses:

* 429 with a fixed message naming the limit (hour, day or concurrent) and ``Retry-After``;
* 503 with the public error text when the ledger cannot be used (fail closed, never 429).

A refusal happens before any turn, query-history row or provider call exists.
"""

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings, get_settings
from app.core.public_safety import PUBLIC_ERROR
from app.db.session import get_db
from app.schemas.conversation import ConversationSubmit
from app.security.principal import ApplicationPrincipal
from app.services.conversation_chat_service import ConversationChatService
from app.services.paid_question_quota import (
    PaidAdmission,
    PaidQuestionQuota,
    QuotaRefused,
    QuotaUnavailable,
    Reason,
)

REFUSAL_MESSAGES: dict[Reason, str] = {
    "hour": "The hourly question limit was reached. Please try again later.",
    "day": "The daily question limit was reached. Please try again later.",
    "concurrent": "Another question is still being answered. Please wait for it to finish.",
}
UNAVAILABLE_RETRY_SECONDS = 5


def get_paid_question_quota(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaidQuestionQuota | None:
    """The request's quota service, or ``None`` in demo mode (which has its own limiter)."""
    if settings.demo_mode:
        return None
    engine = db.bind
    if not isinstance(engine, AsyncEngine):
        raise HTTPException(
            503, PUBLIC_ERROR, headers={"Retry-After": str(UNAVAILABLE_RETRY_SECONDS)}
        )
    return PaidQuestionQuota(engine, settings)


async def admit_or_refuse(quota: PaidQuestionQuota | None, owner: UUID) -> PaidAdmission:
    """Admit one paid question for ``owner`` or raise the 429 / 503 response."""
    if quota is None:
        raise HTTPException(
            503, PUBLIC_ERROR, headers={"Retry-After": str(UNAVAILABLE_RETRY_SECONDS)}
        )
    try:
        return await quota.admit_attempt(owner)
    except QuotaRefused as refusal:
        raise HTTPException(
            429,
            REFUSAL_MESSAGES[refusal.reason],
            headers={"Retry-After": str(refusal.retry_after_seconds)},
        ) from None
    except QuotaUnavailable:
        raise HTTPException(
            503, PUBLIC_ERROR, headers={"Retry-After": str(UNAVAILABLE_RETRY_SECONDS)}
        ) from None


async def admit_turn(
    service: ConversationChatService,
    quota: PaidQuestionQuota | None,
    principal: ApplicationPrincipal,
    conversation_id: UUID,
    body: ConversationSubmit,
) -> PaidAdmission | None:
    """Replay pre-check, then admission. ``None`` means a replay: submit it without an attempt.

    The turn table decides replay, so a retry, reconnect or duplicate of a stored request id is
    never counted and never refused at a limit. A missing or foreign conversation raises
    ``ConversationNotFound`` here, before any quota is spent.
    """
    if await service.has_turn_for_request(principal, conversation_id, body):
        return None
    return await admit_or_refuse(quota, principal.corpus_user_id)
