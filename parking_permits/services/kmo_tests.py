import pytest

from parking_permits.services.kmo import parse_street_name_and_number


@pytest.mark.parametrize(
    "street_address, street_name, street_number",
    [
        ("", "", ""),
        ("Mannerheimintie", "Mannerheimintie", ""),
        ("Mannerheimintie 2", "Mannerheimintie", "2"),
        ("Mannerheimintie 4-5", "Mannerheimintie", "4-5"),
        ("Mannerheimintie 2 A 7", "Mannerheimintie", "2 A 7"),
        ("Mannerheimintie 30,32", "Mannerheimintie", "30,32"),
    ],
)
def test_parse_street_name_and_number_function_returns_correct_result(
    street_address,
    street_name,
    street_number,
):
    assert dict(
        street_name=street_name, street_number=street_number
    ) == parse_street_name_and_number(street_address)
