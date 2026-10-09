from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("stripe")
import stripe  # noqa: E402
from orbit_payments import PaymentRequest, PaymentWebhookError, RefundRequest  # noqa: E402

from orbit_payments_stripe import StripeConfig, StripePaymentProvider  # noqa: E402


def config() -> StripeConfig:
    return StripeConfig(api_key="sk_test_value", webhook_secret="whsec_value")


class FakeStripeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.v1 = SimpleNamespace(
            payment_intents=SimpleNamespace(
                create_async=self.create_payment,
                retrieve_async=self.retrieve_payment,
            ),
            refunds=SimpleNamespace(create_async=self.create_refund),
        )

    async def create_payment(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("payment_intents.create", (payload, kwargs)))
        return {
            "id": "pi_123",
            "amount": payload["amount"],
            "currency": payload["currency"],
            "status": "requires_payment_method",
            "metadata": payload["metadata"],
            "client_secret": "pi_123_secret_token",
            "created": 1_780_000_000,
        }

    async def retrieve_payment(self, payment_id: str) -> dict[str, Any]:
        self.calls.append(("payment_intents.retrieve", (payment_id,)))
        return {
            "id": payment_id,
            "amount": 100,
            "currency": "usd",
            "status": "succeeded",
            "metadata": {"orbit_reference": "order-1"},
        }

    async def create_refund(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("refunds.create", (payload, kwargs)))
        return {
            "id": "re_123",
            "amount": payload["amount"],
            "currency": "usd",
            "status": "succeeded",
        }


@pytest.mark.asyncio
async def test_create_retrieve_refund_and_idempotency_keys() -> None:
    client = FakeStripeClient()
    provider = StripePaymentProvider(config(), client=client)
    payment = await provider.create_payment(
        PaymentRequest(amount_minor=100, currency="USD", reference="order-1")
    )
    retrieved = await provider.get_payment("pi_123")
    refund = await provider.refund(
        RefundRequest(payment_id="pi_123", reference="refund-1", amount_minor=50)
    )

    assert payment.status.value == "requires_action"
    assert payment.client_token == "pi_123_secret_token"
    assert retrieved.status.value == "succeeded"
    assert refund.provider_id == "re_123"
    assert client.calls[0][1][1]["options"]["idempotency_key"] == "order-1"
    assert client.calls[2][1][1]["options"]["idempotency_key"] == "refund-1"
    await provider.aclose()


def test_webhook_maps_only_verified_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    event = {
        "id": "evt_123",
        "type": "payment_intent.succeeded",
        "created": 1_780_000_000,
        "data": {"object": {"object": "payment_intent", "id": "pi_123"}},
    }
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda *args, **kwargs: event)
    provider = StripePaymentProvider(config(), client=FakeStripeClient())
    verified = provider.verify_webhook(b"{}", "t=1,v1=signature")
    assert verified.event_id == "evt_123"
    assert verified.payment_id == "pi_123"

    def reject(*args: Any, **kwargs: Any) -> None:
        raise stripe.SignatureVerificationError("invalid", "signature")

    monkeypatch.setattr(stripe.Webhook, "construct_event", reject)
    with pytest.raises(PaymentWebhookError):
        provider.verify_webhook(b"{}", "bad")


@pytest.mark.asyncio
async def test_provider_requires_startup_without_injected_client() -> None:
    provider = StripePaymentProvider(config())
    with pytest.raises(RuntimeError):
        await provider.get_payment("pi_123")
    await provider.aclose()
