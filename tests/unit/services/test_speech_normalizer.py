import pytest

from boloride.services.speech_normalizer import normalize_for_speech


@pytest.mark.parametrize(
    ("source", "spoken"),
    [
        ("Fare ₹245", "Fare 245 rupees"),
        ("Fare ₹245.50", "Fare 245 rupees and 50 paise"),
        ("RJ20AB1234", "R J 20, A B, 1 2 3 4"),
        ("Pickup 5:30 PM", "Pickup 5:30 in the evening"),
        ("Pickup 7 AM", "Pickup 7 in the morning"),
        ("Distance 1.2 km", "Distance 1.2 kilometers"),
        ("Call 9876543210", "Call 9 8 7 6 5 4 3 2 1 0"),
        ("Ji, pickup confirm kar doon?", "Ji, pickup confirm kar doon?"),
    ],
)
def test_structured_values_are_normalized_deterministically(source, spoken):
    original = source
    assert normalize_for_speech(source) == spoken
    assert source == original


def test_basic_markdown_list_markers_are_not_spoken():
    assert normalize_for_speech("- First\n- Second\n**Done**") == "First\nSecond\nDone"
