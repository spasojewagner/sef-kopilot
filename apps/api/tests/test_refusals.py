"""A request the models refuse: 422 with where and why, and never what it held."""

from __future__ import annotations

from httpx import AsyncClient

SENT = "Tajna-4711-lozinka"


async def test_a_value_refused_is_not_sent_back(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": "ana@primer.example", "password": "4711-kratka", "organization_name": "P"},
    )

    assert response.status_code == 422
    assert "4711" not in response.text
    (error,) = response.json()["detail"]
    assert error == {
        "type": "string_too_short",
        "loc": ["body", "password"],
        "msg": "String should have at least 12 characters",
        "ctx": {"min_length": 12},
    }


async def test_a_field_missing_does_not_send_back_the_object_around_it(
    client: AsyncClient,
) -> None:
    """The error of a field missing holds the whole object, here with a password under a name
    that is not the field's."""
    response = await client.post("/auth/login", json={"lozinka": SENT, "mail": SENT})

    assert response.status_code == 422
    assert SENT not in response.text
    assert [(error["type"], error["loc"]) for error in response.json()["detail"]] == [
        ("missing", ["body", "email"]),
        ("missing", ["body", "password"]),
    ]


async def test_a_body_that_is_not_json_is_refused_without_it(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        content=f'{{"email": "ana@primer.example", "password": "{SENT}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert SENT not in response.text
    assert response.json()["detail"][0]["type"] == "json_invalid"
