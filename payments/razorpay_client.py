"""
payments/razorpay_client.py
Rastlina — Razorpay client wrapper.
Centralised here so both payments/ and orders/ import from one place.
"""

import decimal
import logging

import razorpay
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_client() -> razorpay.Client:
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', None)
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', None)
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay credentials not configured in settings.")
    return razorpay.Client(auth=(key_id, key_secret))


def create_order(amount, currency: str = 'INR', *, receipt: str | None = None) -> dict:
    """
    Create a Razorpay order. amount can be Decimal, float, or int (in rupees).
    Returns the full Razorpay order dict including 'id', 'amount', 'currency'.
    """
    if isinstance(amount, decimal.Decimal):
        amount = float(amount)
    amount_paise = int(round(amount * 100))
    client = _get_client()
    payload = {
        'amount': amount_paise,
        'currency': currency,
        'payment_capture': 1,  # auto-capture
    }
    if receipt:
        payload['receipt'] = receipt
    rzp_order = client.order.create(payload)
    logger.info("Razorpay order created: %s (₹%s)", rzp_order['id'], amount)
    return rzp_order


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """
    Verify the Razorpay payment signature. Returns True if valid.
    """
    client = _get_client()
    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })
        logger.info("Signature verified for order %s", razorpay_order_id)
        return True
    except Exception as e:
        logger.warning("Signature verification failed for order %s: %s", razorpay_order_id, e)
        return False


def verify_webhook_signature(body: str, signature: str) -> bool:
    """
    Verify a Razorpay webhook payload signature.
    Raises on failure so caller can return 400.
    """
    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', None)
    if not webhook_secret:
        raise RuntimeError("RAZORPAY_WEBHOOK_SECRET not set in settings.")
    client = _get_client()
    client.utility.verify_webhook_signature(body, signature, webhook_secret)
    return True


def refund_payment(razorpay_payment_id: str, amount_rupees: decimal.Decimal) -> dict:
    """
    Initiate a full or partial refund. amount_rupees in rupees (Decimal).
    Returns the Razorpay refund object.
    """
    client = _get_client()
    amount_paise = int(round(float(amount_rupees) * 100))
    refund = client.payment.refund(razorpay_payment_id, {'amount': amount_paise})
    logger.info(
        "Refund initiated: payment=%s amount_paise=%s refund_id=%s",
        razorpay_payment_id, amount_paise, refund.get('id'),
    )
    return refund


def fetch_payment(razorpay_payment_id: str) -> dict:
    """Fetch a Razorpay payment object by ID."""
    client = _get_client()
    return client.payment.fetch(razorpay_payment_id)
