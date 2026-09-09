from collections import Counter

from boloride.domain.models.fleet import (
    CITY_CENTRES,
    FLEET_SEED_VERSION,
    VEHICLE_COUNTS,
    DriverAvailability,
    generate_demo_fleet,
)


def test_demo_fleet_generation_is_exact_and_deterministic() -> None:
    first = generate_demo_fleet()
    second = generate_demo_fleet()

    assert first == second
    assert len(first) == 1060
    assert Counter(member.vehicle_type_code for member in first) == VEHICLE_COUNTS
    assert len({member.driver_id for member in first}) == 1060
    assert len({member.vehicle_id for member in first}) == 1060
    assert len({member.seed_key for member in first}) == 1060
    assert all(member.seed_key.startswith(FLEET_SEED_VERSION) for member in first)
    assert all(member.availability is DriverAvailability.AVAILABLE for member in first)


def test_demo_fleet_uses_approved_city_centres_and_small_offsets() -> None:
    centres = {(centre.state, centre.city): centre for centre in CITY_CENTRES}
    for member in generate_demo_fleet():
        centre = centres[(member.state, member.city)]
        assert abs(member.latitude - centre.latitude) <= 0.010000
        assert abs(member.longitude - centre.longitude) <= 0.010000
        assert member.registration_number.startswith(centre.registration_prefix)
