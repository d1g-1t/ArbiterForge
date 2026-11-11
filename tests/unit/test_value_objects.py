from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbiterforge.domain.value_objects import (
    _INN10_WEIGHTS,
    _INN12_WEIGHTS_1,
    _INN12_WEIGHTS_2,
    EventEnvelope,
    Inn,
    Institution,
    Money,
    Ogrn,
    _check_digit,
    is_valid_inn,
    is_valid_ogrn,
)


def make_inn10(body: str) -> str:
    return body + str(_check_digit(body, _INN10_WEIGHTS))


def make_inn12(body: str) -> str:
    first = str(_check_digit(body, _INN12_WEIGHTS_1))
    return body + first + str(_check_digit(body + first, _INN12_WEIGHTS_2))


def make_ogrn(body: str) -> str:
    return body + str(int(body) % 11 % 10)


def make_ogrnip(body: str) -> str:
    return body + str(int(body) % 13 % 10)


@given(st.text(alphabet="0123456789", min_size=9, max_size=9))
def test_generated_inn10_valid_and_any_other_check_digit_invalid(body: str) -> None:
    inn = make_inn10(body)
    assert is_valid_inn(inn)
    for digit in "0123456789":
        if digit != inn[-1]:
            assert not is_valid_inn(inn[:-1] + digit)


@given(st.text(alphabet="0123456789", min_size=10, max_size=10))
def test_generated_inn12_valid(body: str) -> None:
    inn = make_inn12(body)
    assert is_valid_inn(inn)
    assert not is_valid_inn(inn[:-1] + str((int(inn[-1]) + 1) % 10))


@given(st.text(alphabet="0123456789", min_size=12, max_size=12))
def test_generated_ogrn_valid(body: str) -> None:
    ogrn = make_ogrn(body)
    assert is_valid_ogrn(ogrn)
    assert not is_valid_ogrn(ogrn[:-1] + str((int(ogrn[-1]) + 1) % 10))


@given(st.text(alphabet="0123456789", min_size=14, max_size=14))
def test_generated_ogrnip_valid(body: str) -> None:
    ogrnip = make_ogrnip(body)
    assert is_valid_ogrn(ogrnip)
    assert not is_valid_ogrn(ogrnip[:-1] + str((int(ogrnip[-1]) + 1) % 10))


@pytest.mark.parametrize("value", ["", "123", "12345678901", "abcdefghij", "0000123450 "])
def test_malformed_inn(value: str) -> None:
    assert not is_valid_inn(value)


@pytest.mark.parametrize("value", ["", "123", "10000000123", "100000001234X"])
def test_malformed_ogrn(value: str) -> None:
    assert not is_valid_ogrn(value)


def test_value_objects_validate() -> None:
    assert Inn("0000123450").value == "0000123450"
    assert Ogrn("1000000012341").value == "1000000012341"
    with pytest.raises(ValueError, match="INN"):
        Inn("0000123451")
    with pytest.raises(ValueError, match="OGRN"):
        Ogrn("1000000012342")


def test_money() -> None:
    assert Money(Decimal("10.50"), "USD").currency == "USD"
    with pytest.raises(ValueError, match="non-negative"):
        Money(Decimal("-1"))
    with pytest.raises(ValueError, match="ISO 4217"):
        Money(Decimal("1"), "rub")


def test_institution_flags_and_envelope() -> None:
    assert Institution.ICAC_MKAS.is_institutional
    assert not Institution.AD_HOC.is_institutional
    env = EventEnvelope(
        "e", "a", "T", 1, "X", {}, "2026-01-01T00:00:00+00:00", None, {"organization_id": "o"}
    )
    assert env.organization_id == "o"
    assert env.to_dict()["metadata"] == {"organization_id": "o"}
