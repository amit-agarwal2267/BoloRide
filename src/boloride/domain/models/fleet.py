from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, NAMESPACE_URL, uuid5


FLEET_SEED_VERSION = "prototype-v1-fleet-1"
FLEET_NAMESPACE = uuid5(NAMESPACE_URL, "https://boloride.example/demo-fleet")


class DriverAvailability(StrEnum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    ON_TRIP = "on_trip"


@dataclass(frozen=True, slots=True)
class CityCentre:
    state: str
    city: str
    registration_prefix: str
    latitude: Decimal
    longitude: Decimal


@dataclass(frozen=True, slots=True)
class DemoFleetMember:
    ordinal: int
    driver_id: UUID
    vehicle_id: UUID
    seed_key: str
    driver_name: str
    availability: DriverAvailability
    latitude: Decimal
    longitude: Decimal
    city: str
    state: str
    vehicle_type_code: str
    registration_number: str


CITY_CENTRES = (
    CityCentre("Rajasthan", "Kota", "RJ", Decimal("25.2138"), Decimal("75.8648")),
    CityCentre("Rajasthan", "Jaipur", "RJ", Decimal("26.9124"), Decimal("75.7873")),
    CityCentre("Rajasthan", "Jodhpur", "RJ", Decimal("26.2389"), Decimal("73.0243")),
    CityCentre("Rajasthan", "Udaipur", "RJ", Decimal("24.5854"), Decimal("73.7125")),
    CityCentre("Rajasthan", "Ajmer", "RJ", Decimal("26.4499"), Decimal("74.6399")),
    CityCentre("Uttar Pradesh", "Lucknow", "UP", Decimal("26.8467"), Decimal("80.9462")),
    CityCentre("Uttar Pradesh", "Kanpur", "UP", Decimal("26.4499"), Decimal("80.3319")),
    CityCentre("Uttar Pradesh", "Agra", "UP", Decimal("27.1767"), Decimal("78.0081")),
    CityCentre("Uttar Pradesh", "Noida", "UP", Decimal("28.5355"), Decimal("77.3910")),
    CityCentre("Uttar Pradesh", "Prayagraj", "UP", Decimal("25.4358"), Decimal("81.8463")),
    CityCentre("Uttar Pradesh", "Varanasi", "UP", Decimal("25.3176"), Decimal("82.9739")),
    CityCentre("Madhya Pradesh", "Indore", "MP", Decimal("22.7196"), Decimal("75.8577")),
    CityCentre("Madhya Pradesh", "Bhopal", "MP", Decimal("23.2599"), Decimal("77.4126")),
    CityCentre("Madhya Pradesh", "Gwalior", "MP", Decimal("26.2183"), Decimal("78.1828")),
    CityCentre("Madhya Pradesh", "Jabalpur", "MP", Decimal("23.1815"), Decimal("79.9864")),
    CityCentre("Madhya Pradesh", "Ujjain", "MP", Decimal("23.1765"), Decimal("75.7885")),
    CityCentre("Punjab", "Ludhiana", "PB", Decimal("30.9010"), Decimal("75.8573")),
    CityCentre("Punjab", "Amritsar", "PB", Decimal("31.6340"), Decimal("74.8723")),
    CityCentre("Punjab", "Jalandhar", "PB", Decimal("31.3260"), Decimal("75.5762")),
    CityCentre("Punjab", "Patiala", "PB", Decimal("30.3398"), Decimal("76.3869")),
    CityCentre("Punjab", "Mohali", "PB", Decimal("30.7046"), Decimal("76.7179")),
)

VEHICLE_COUNTS = {
    "auto": 200,
    "mini": 500,
    "sedan": 300,
    "suv": 50,
    "premium": 10,
}

_FIRST_NAMES = (
    "Aarav", "Aditya", "Aman", "Arjun", "Deepak", "Dev", "Harish", "Ishaan",
    "Kabir", "Karan", "Manish", "Mohan", "Naveen", "Nikhil", "Pranav", "Rahul",
    "Rajesh", "Ravi", "Rohan", "Sanjay", "Sunil", "Varun", "Vijay", "Vikram",
)
_LAST_NAMES = (
    "Bansal", "Chauhan", "Gupta", "Jain", "Joshi", "Kapoor", "Khan", "Kumar",
    "Meena", "Mishra", "Patel", "Rathore", "Saini", "Saxena", "Sharma", "Singh",
    "Tiwari", "Verma", "Yadav",
)


def generate_demo_fleet() -> tuple[DemoFleetMember, ...]:
    members: list[DemoFleetMember] = []
    ordinal = 0
    for vehicle_type_code, count in VEHICLE_COUNTS.items():
        for _ in range(count):
            centre = CITY_CENTRES[ordinal % len(CITY_CENTRES)]
            seed_key = f"{FLEET_SEED_VERSION}:{ordinal:04d}"
            # A deterministic grid within roughly 1.5 km of each city centre.
            lat_step = Decimal((ordinal * 37) % 21 - 10) * Decimal("0.0010")
            lon_step = Decimal((ordinal * 53) % 21 - 10) * Decimal("0.0010")
            first = _FIRST_NAMES[ordinal % len(_FIRST_NAMES)]
            last = _LAST_NAMES[(ordinal // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
            district = 10 + (ordinal % 90)
            series = chr(65 + (ordinal // 26) % 26) + chr(65 + ordinal % 26)
            number = 1000 + ordinal
            registration = f"{centre.registration_prefix}{district:02d}{series}{number:04d}"
            members.append(
                DemoFleetMember(
                    ordinal=ordinal,
                    driver_id=uuid5(FLEET_NAMESPACE, f"driver:{seed_key}"),
                    vehicle_id=uuid5(FLEET_NAMESPACE, f"vehicle:{seed_key}"),
                    seed_key=seed_key,
                    driver_name=f"{first} {last}",
                    availability=DriverAvailability.AVAILABLE,
                    latitude=(centre.latitude + lat_step).quantize(Decimal("0.000001")),
                    longitude=(centre.longitude + lon_step).quantize(Decimal("0.000001")),
                    city=centre.city,
                    state=centre.state,
                    vehicle_type_code=vehicle_type_code,
                    registration_number=registration,
                )
            )
            ordinal += 1
    return tuple(members)
