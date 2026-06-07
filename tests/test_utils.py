"""Unit tests for utility helpers."""
from __future__ import annotations

import pytest

from src.utils import deduplicate, normalise_domain, render_email


class TestNormaliseDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("stripe.com", "stripe.com"),
            ("https://stripe.com", "stripe.com"),
            ("http://stripe.com/payments", "stripe.com"),
            ("https://www.stripe.com", "stripe.com"),
            ("STRIPE.COM", "stripe.com"),
            ("  stripe.com  ", "stripe.com"),
        ],
    )
    def test_normalise(self, raw: str, expected: str):
        assert normalise_domain(raw) == expected


class TestDeduplicate:
    def test_removes_exact_duplicates(self):
        items = ["a", "b", "a", "c", "b"]
        result = deduplicate(items, key_fn=lambda x: x)
        assert result == ["a", "b", "c"]

    def test_preserves_insertion_order(self):
        items = [3, 1, 2, 1, 3]
        result = deduplicate(items, key_fn=lambda x: x)
        assert result == [3, 1, 2]

    def test_empty_list(self):
        assert deduplicate([], key_fn=lambda x: x) == []

    def test_key_fn_applied(self):
        items = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 1, "v": "c"}]
        result = deduplicate(items, key_fn=lambda x: x["id"])
        assert len(result) == 2
        assert result[0]["v"] == "a"


class TestRenderEmail:
    def test_subject_contains_company(self):
        subject, _ = render_email("John Doe", "Stripe", "CEO")
        assert "Stripe" in subject

    def test_body_contains_first_name(self):
        _, body = render_email("John Doe", "Stripe", "CEO")
        assert "John" in body
        assert "Doe" not in body

    def test_body_contains_title(self):
        _, body = render_email("Jane Smith", "Adyen", "VP Sales")
        assert "VP Sales" in body

    def test_body_contains_company(self):
        _, body = render_email("Jane Smith", "Adyen", "VP Sales")
        assert "Adyen" in body

    def test_subject_format(self):
        subject, _ = render_email("X", "Stripe", "CTO")
        assert subject == "Quick idea for Stripe"

    def test_empty_name_uses_there(self):
        _, body = render_email("", "Stripe", "CTO")
        assert "Hi there" in body
