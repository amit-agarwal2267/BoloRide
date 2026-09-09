from datetime import datetime
from decimal import Decimal
from uuid import UUID

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.offer import AppliedOfferSnapshot, DiscountType
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.integrations.rideprovider.base import RideBookingRequest, RideBookingResult

SNAPSHOT_VERSION = 1


def serialize_authorization(request: RideBookingRequest, quote: Quote) -> dict:
    pricing = quote.pricing
    offer = pricing.applied_offer
    return {
        "version": SNAPSHOT_VERSION,
        "request": {
            "request_id": str(request.request_id),
            "pickup": _serialize_location(request.pickup),
            "destination": _serialize_location(request.destination),
            "requested_ride_at": request.requested_ride_at.isoformat(),
            "passenger_count": request.passenger_count,
            "vehicle_type_code": request.vehicle_type_code,
        },
        "quote": {
            "id": str(quote.id),
            "session_id": quote.session_id,
            "request_fingerprint": quote.request_fingerprint,
            "quoted_at": quote.quoted_at.isoformat(),
            "expires_at": quote.expires_at.isoformat(),
            "pricing": {
                "pricing_rule_id": str(pricing.pricing_rule_id),
                "vehicle_type_code": pricing.vehicle_type_code,
                "route_distance_meters": pricing.route_distance_meters,
                "route_duration_seconds": pricing.route_duration_seconds,
                "route_provider": pricing.route_provider,
                "components": [{"type": item.component_type.value, "amount": str(item.amount)} for item in pricing.components],
                "toll_status": pricing.toll_status.value,
                "estimated_total": str(pricing.estimated_total),
                "currency": pricing.currency,
                "pre_discount_estimated_total": str(pricing.pre_discount_estimated_total) if pricing.pre_discount_estimated_total is not None else None,
                "offer": _serialize_offer(offer) if offer else None,
            },
        },
    }


def deserialize_authorization(value: object) -> tuple[RideBookingRequest, Quote]:
    try:
        if not isinstance(value, dict) or value.get("version") != SNAPSHOT_VERSION:
            raise ValueError("unsupported snapshot version")
        request_data = value["request"]
        quote_data = value["quote"]
        pricing_data = quote_data["pricing"]
        components = tuple(FareComponent(FareComponentType(item["type"]), Decimal(item["amount"])) for item in pricing_data["components"])
        offer_data = pricing_data["offer"]
        offer = AppliedOfferSnapshot(
            UUID(offer_data["offer_id"]), offer_data["code"], offer_data["display_name"],
            DiscountType(offer_data["discount_type"]), Decimal(offer_data["percentage"]),
            Decimal(offer_data["maximum_discount"]), Decimal(offer_data["discount_amount"]),
            offer_data["currency"], int(offer_data["version"]),
        ) if offer_data else None
        pricing = PricingResult(
            UUID(pricing_data["pricing_rule_id"]), pricing_data["vehicle_type_code"],
            int(pricing_data["route_distance_meters"]), pricing_data["route_duration_seconds"],
            pricing_data["route_provider"], components, TollStatus(pricing_data["toll_status"]),
            Decimal(pricing_data["estimated_total"]), pricing_data["currency"],
            Decimal(pricing_data["pre_discount_estimated_total"]) if pricing_data["pre_discount_estimated_total"] is not None else None,
            offer,
        )
        quote = Quote(
            UUID(quote_data["id"]), quote_data["session_id"], quote_data["request_fingerprint"],
            pricing, datetime.fromisoformat(quote_data["quoted_at"]), datetime.fromisoformat(quote_data["expires_at"]),
        )
        request = RideBookingRequest(
            UUID(request_data["request_id"]), _deserialize_location(request_data["pickup"]),
            _deserialize_location(request_data["destination"]), datetime.fromisoformat(request_data["requested_ride_at"]),
            int(request_data["passenger_count"]), request_data["vehicle_type_code"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainValidationError("invalid booking authorization recovery snapshot") from exc
    if request.request_id != UUID(str(value["request"]["request_id"])) or quote.id != UUID(str(value["quote"]["id"])):
        raise DomainValidationError("booking authorization snapshot identity mismatch")
    return request, quote


def serialize_provider_result(result: RideBookingResult) -> dict:
    return {"version": 1, "provider": result.provider, "provider_booking_id": result.provider_booking_id, "driver_name": result.driver_name, "vehicle_description": result.vehicle_description}


def deserialize_provider_result(value: object) -> RideBookingResult:
    try:
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported provider snapshot version")
        result = RideBookingResult(value["provider"], value["provider_booking_id"], value["driver_name"], value["vehicle_description"])
        if not result.provider.strip() or not result.provider_booking_id.strip():
            raise ValueError("blank provider identity")
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainValidationError("invalid provider booking recovery snapshot") from exc


def _serialize_location(location: ResolvedLocation) -> dict:
    return {"address": location.address, "latitude": str(location.latitude), "longitude": str(location.longitude), "display_name": location.display_name, "provider": location.provider, "provider_place_id": location.provider_place_id, "place_types": list(location.place_types) if location.place_types else None, "country": location.country}


def _deserialize_location(value: dict) -> ResolvedLocation:
    return ResolvedLocation(value["address"], Decimal(value["latitude"]), Decimal(value["longitude"]), value.get("display_name"), value.get("provider"), value.get("provider_place_id"), tuple(value["place_types"]) if value.get("place_types") else None, value.get("country"))


def _serialize_offer(offer: AppliedOfferSnapshot) -> dict:
    return {"offer_id": str(offer.offer_id), "code": offer.code, "display_name": offer.display_name, "discount_type": offer.discount_type.value, "percentage": str(offer.percentage), "maximum_discount": str(offer.maximum_discount), "discount_amount": str(offer.discount_amount), "currency": offer.currency, "version": offer.version}
