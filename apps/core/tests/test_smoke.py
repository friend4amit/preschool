import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_healthz_is_cheap_and_ok(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.content == b"ok"


def test_home_renders_through_the_public_layout(client):
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"Aaroham" in response.content
