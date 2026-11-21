"""An always-admitting stand-in for the paid-question quota, for tests of route behavior that do
not involve a database (M0-SEC ticket 06). The real quota is tested against PostgreSQL in
``tests/security/test_paid_question_quota.py`` and ``tests/security/test_paid_question_routes.py``."""

from uuid import UUID, uuid4

from app.core.paid_execution import PaidExecutionMarker
from app.services.paid_question_quota import PaidAdmission


class AdmitAllQuota:
    """Admits every question and records how each attempt ended."""

    def __init__(self) -> None:
        self.ended: list[bool] = []  # True: finished (a provider request began), False: released

    async def admit_attempt(self, owner: UUID) -> PaidAdmission:
        return PaidAdmission(self, uuid4())  # type: ignore[arg-type]

    async def settle(self, attempt_id: UUID, marker: PaidExecutionMarker) -> None:
        self.ended.append(marker.started)
