from collections import deque

from boloride.integrations.rideprovider.base import (
    ProviderCreateOutcome,
    ProviderCreateStatus,
    ProviderReconciliationOutcome,
    ProviderReconciliationStatus,
    RideBookingRequest,
    RideBookingResult,
)


class MockRideProvider:
    provider_name = "mock"
    supports_safe_retry_after_definitive_absence = True

    def __init__(self) -> None:
        self._bookings: dict[str, RideBookingResult] = {}
        self._create_outcomes: deque[tuple[ProviderCreateStatus, bool]] = deque()
        self._reconciliation_outcomes: deque[ProviderReconciliationStatus] = deque()
        self.create_call_count = 0
        self.reconciliation_call_count = 0
        self.create_idempotency_keys: list[str] = []
        self.create_requests: list[RideBookingRequest] = []

    @property
    def logical_booking_count(self) -> int:
        return len(self._bookings)

    def queue_create(self, status: ProviderCreateStatus, *, booking_created: bool = False) -> None:
        self._create_outcomes.append((status, booking_created))

    def queue_reconciliation(self, status: ProviderReconciliationStatus) -> None:
        self._reconciliation_outcomes.append(status)

    async def create_booking(
        self, request: RideBookingRequest, *, idempotency_key: str
    ) -> ProviderCreateOutcome:
        self.create_call_count += 1
        self.create_idempotency_keys.append(idempotency_key)
        self.create_requests.append(request)
        existing = self._bookings.get(idempotency_key)
        if existing is not None:
            return ProviderCreateOutcome(ProviderCreateStatus.CONFIRMED, existing)
        status, booking_created = (
            self._create_outcomes.popleft()
            if self._create_outcomes
            else (ProviderCreateStatus.CONFIRMED, True)
        )
        booking = RideBookingResult(
            provider=self.provider_name,
            provider_booking_id=f"mock-{idempotency_key}",
            driver_name="Amit Kumar",
            vehicle_description="White Maruti Dzire, RJ 20 AB 1234",
        )
        if status is ProviderCreateStatus.CONFIRMED or booking_created:
            self._bookings[idempotency_key] = booking
        if status is ProviderCreateStatus.CONFIRMED:
            return ProviderCreateOutcome(status, booking)
        return ProviderCreateOutcome(status, failure_category=status.value)

    async def reconcile_booking(self, idempotency_key: str) -> ProviderReconciliationOutcome:
        self.reconciliation_call_count += 1
        if self._reconciliation_outcomes:
            status = self._reconciliation_outcomes.popleft()
            if status is ProviderReconciliationStatus.UNKNOWN:
                return ProviderReconciliationOutcome(status, failure_category="reconciliation_unknown")
            if status is ProviderReconciliationStatus.DEFINITIVELY_ABSENT:
                return ProviderReconciliationOutcome(status)
        booking = self._bookings.get(idempotency_key)
        if booking is None:
            return ProviderReconciliationOutcome(ProviderReconciliationStatus.DEFINITIVELY_ABSENT)
        return ProviderReconciliationOutcome(ProviderReconciliationStatus.CONFIRMED, booking)
