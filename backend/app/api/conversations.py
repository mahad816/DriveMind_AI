"""Private PostgreSQL conversation metadata, durable turns and request-owned generation."""

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_normal_mode
from app.api.session_dependencies import (
    get_application_session_service,
    require_application_principal,
    require_session_mutation,
)
from app.db.session import get_db
from app.core.public_safety import public_error_detail
from app.core.config import Settings, get_settings
from app.services.conversation_chat_service import ConversationChatService
from app.schemas.conversation import (
    ConversationCreate,
    ConversationRead,
    ConversationList,
    ConversationDetail,
    ConversationRename,
    ConversationDelete,
    ConversationSubmit,
    ConversationSubmission,
    ConversationTurnStatus,
    ConversationInterrupt,
)
from app.security.principal import ApplicationPrincipal
from app.services.application_session_service import ApplicationSessionService
from app.services.conversation_repository import (
    ConversationNotFound,
    ConversationConflict,
    ConversationVersionConflict,
)
from app.services.conversation_service import (
    ConversationService,
    InvalidConversationCursor,
    ConversationSessionExpired,
)

PRIVATE_HEADERS = {"Cache-Control": "private, no-store, max-age=0", "Vary": "Cookie"}


class ConversationRoute(APIRoute):
    """Apply private caching and safe errors even when a dependency rejects."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def private_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except HTTPException as exc:
                response = JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                )
            except RequestValidationError as exc:
                response = JSONResponse(
                    {
                        "detail": [
                            {"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
                            for e in exc.errors()
                        ]
                    },
                    status_code=422,
                )
            except ConversationNotFound:
                response = JSONResponse({"detail": "Conversation not found."}, status_code=404)
            except ConversationVersionConflict:
                response = JSONResponse(
                    {"detail": "Conversation metadata version is stale."}, status_code=409
                )
            except ConversationConflict:
                response = JSONResponse(
                    {"detail": "Conversation request conflicts with existing state."},
                    status_code=409,
                )
            except InvalidConversationCursor:
                response = JSONResponse({"detail": "Invalid pagination cursor."}, status_code=422)
            except ConversationSessionExpired:
                response = JSONResponse(
                    {"detail": "A valid application session is required."}, status_code=401
                )
            except Exception as exc:
                # Includes persistence and stored-response validation errors. Never
                # reflect SQL, provider bodies, submitted values or internal state.
                public_error_detail(exc)
                response = JSONResponse(
                    {"detail": "Conversation storage is temporarily unavailable."}, status_code=503
                )
            response.headers.update(PRIVATE_HEADERS)
            return response

        return private_handler


router = APIRouter(
    prefix="/conversations",
    route_class=ConversationRoute,
    dependencies=[Depends(require_normal_mode)],
)


def get_conversation_service(db: AsyncSession = Depends(get_db)) -> ConversationService:
    return ConversationService(db)


async def require_conversation_mutation(
    request: Request,
    service: ApplicationSessionService = Depends(get_application_session_service),
) -> ApplicationPrincipal:
    # Existing policy: missing/invalid principal is 401 before CSRF/Origin checks.
    await require_application_principal(request, service)
    return await require_session_mutation(request, service)


@router.post(
    "",
    response_model=ConversationRead,
    status_code=201,
    responses={200: {"model": ConversationRead, "description": "Idempotent replay"}},
)
async def create_conversation(
    body: ConversationCreate,
    response: Response,
    principal: ApplicationPrincipal = Depends(require_conversation_mutation),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    result, replayed = await service.create(principal, body)
    response.status_code = 200 if replayed else 201
    return result


@router.get("", response_model=ConversationList)
async def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    principal: ApplicationPrincipal = Depends(require_application_principal),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationList:
    return await service.list_owned(principal, limit=limit, cursor=cursor)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def conversation_detail(
    conversation_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    before_sequence: int | None = Query(default=None, ge=1, le=9223372036854775807),
    principal: ApplicationPrincipal = Depends(require_application_principal),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetail:
    return await service.detail(
        principal, conversation_id, limit=limit, before_sequence=before_sequence
    )


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def rename_conversation(
    conversation_id: UUID,
    body: ConversationRename,
    principal: ApplicationPrincipal = Depends(require_conversation_mutation),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationRead:
    return await service.rename(principal, conversation_id, body)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    body: ConversationDelete,
    principal: ApplicationPrincipal = Depends(require_conversation_mutation),
    service: ConversationService = Depends(get_conversation_service),
) -> Response:
    await service.delete(principal, conversation_id, body.expected_metadata_version)
    return Response(status_code=204)


def get_conversation_chat_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationChatService:
    return ConversationChatService(db, settings)


@router.post(
    "/{conversation_id}/turns",
    response_model=ConversationSubmission,
    responses={202: {"model": ConversationSubmission}, 503: {"model": ConversationSubmission}},
)
async def submit_conversation_turn(
    conversation_id: UUID,
    body: ConversationSubmit,
    response: Response,
    principal: ApplicationPrincipal = Depends(require_conversation_mutation),
    service: ConversationChatService = Depends(get_conversation_chat_service),
) -> ConversationSubmission:
    result, status = await service.submit(principal, conversation_id, body)
    response.status_code = status
    if status == 202:
        response.headers["Location"] = (
            f"{service.settings.api_prefix}/conversations/{conversation_id}/turns/{result.turn.id}"
        )
    return result


@router.get("/{conversation_id}/turns/{turn_id}", response_model=ConversationTurnStatus)
async def conversation_turn_status(
    conversation_id: UUID,
    turn_id: UUID,
    principal: ApplicationPrincipal = Depends(require_application_principal),
    service: ConversationChatService = Depends(get_conversation_chat_service),
) -> ConversationTurnStatus:
    return await service.status(principal, conversation_id, turn_id)


@router.post("/{conversation_id}/turns/{turn_id}/interrupt", response_model=ConversationTurnStatus)
async def interrupt_expired_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    body: ConversationInterrupt,
    principal: ApplicationPrincipal = Depends(require_conversation_mutation),
    service: ConversationChatService = Depends(get_conversation_chat_service),
) -> ConversationTurnStatus:
    return await service.interrupt_expired(principal, conversation_id, turn_id)
