"""
orders/models.py
Rastlina — Production-hardened order models.

Idempotency flags on Order (never rely on PaymentLog for these):
  stock_deducted     — stock was deducted after payment capture
  stock_restored     — stock was restored on cancellation/return
  coupon_applied     — coupon uses_count was incremented (at capture, not checkout)
  exchange_consumed  — exchange code was burned (at capture, not checkout)

ReturnRequest  = Exchange-request flow (defective item → exchange code)
OrderReturnRequest = Physical return flow (admin handles refund)
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# ORDER
# ─────────────────────────────────────────────────────────────────────────────

class Order(models.Model):
    PAYMENT_STATUS = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
        ('Refunded', 'Refunded'),
        ('Refund Pending', 'Refund Pending'),
    ]
    ORDER_STATUS = [
        ('Pending', 'Pending'),          # Pre-payment draft — hidden from user order list
        ('Processing', 'Processing'),    # Payment captured — awaiting admin confirmation
        ('Confirmed', 'Confirmed'),      # Admin confirmed — being packed
        ('Shipped', 'Shipped'),          # In transit
        ('Delivered', 'Delivered'),      # Delivered to customer
        ('Cancelled', 'Cancelled'),      # Cancelled
    ]
    PAYMENT_METHOD = [('Online', 'Online')]

    # ── User (null = guest order) ─────────────────────────────────────────────
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
    )

    # ── Customer info (stored flat for guest support) ─────────────────────────
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    # ── Shipping ──────────────────────────────────────────────────────────────
    shipping_address = models.TextField()
    apartment = models.CharField(max_length=255, blank=True)
    landmark = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='India')

    # ── Financials ────────────────────────────────────────────────────────────
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cod_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    coupon_code = models.CharField(max_length=50, blank=True)
    exchange_code_used = models.CharField(max_length=20, blank=True)

    # ── Status ────────────────────────────────────────────────────────────────
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD, default='Online'
    )
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='Pending'
    )
    order_status = models.CharField(
        max_length=20, choices=ORDER_STATUS, default='Pending'
    )

    # ── Idempotency flags (authoritative — do NOT rely on PaymentLog) ─────────
    stock_deducted = models.BooleanField(
        default=False, db_index=True,
        help_text="True once stock has been deducted after payment. Never set manually.",
    )
    stock_restored = models.BooleanField(
        default=False,
        help_text="True once stock has been restored (cancellation/return). Never set manually.",
    )
    coupon_applied = models.BooleanField(
        default=False,
        help_text="True once coupon uses_count has been incremented. Never set manually.",
    )
    exchange_consumed = models.BooleanField(
        default=False,
        help_text="True once exchange code has been marked used. Never set manually.",
    )

    # ── Policy ────────────────────────────────────────────────────────────────
    accepted_return_policy = models.BooleanField(
        default=True,
        help_text="Customer accepted 15-day exchange policy at checkout",
    )

    # ── Razorpay ──────────────────────────────────────────────────────────────
    razorpay_receipt = models.CharField(
        max_length=40, unique=True, null=True, blank=True, editable=False,
    )
    razorpay_order_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )
    razorpay_payment_id = models.CharField(max_length=100, null=True, blank=True)

    # ── Tracking ──────────────────────────────────────────────────────────────
    tracking_link = models.URLField(max_length=500, blank=True, null=True)
    tracking_note = models.TextField(blank=True, null=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        customer = self.email or f"{self.first_name} {self.last_name}".strip() or "Guest"
        return f"Order #{self.id} — {customer}"

    @property
    def is_guest(self):
        return self.user is None


# ─────────────────────────────────────────────────────────────────────────────
# ORDER ITEM
# ─────────────────────────────────────────────────────────────────────────────

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(
        'store.Product', on_delete=models.SET_NULL, null=True, blank=True
    )
    variant = models.ForeignKey(
        'store.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True
    )
    # Snapshot fields — preserved even if product/variant is deleted
    product_name = models.CharField(max_length=255)
    variant_label = models.CharField(max_length=200, blank=True,
        help_text="e.g. 'Medium / Sage Green'")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    image_url = models.TextField(blank=True)

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def item_total(self):
        return self.price * self.quantity


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE CODE
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeCode(models.Model):
    """
    Generated when admin approves a ReturnRequest (defective item → exchange).
    Customer uses this code at checkout to get equal/higher-value replacement.
    """
    code = models.CharField(
        max_length=20, unique=True,
        help_text="Auto-generated unique code given to customer",
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='exchange_codes'
    )
    original_order_value = models.DecimalField(max_digits=10, decimal_places=2)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"RST-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} (Order #{self.order_id})"


# ─────────────────────────────────────────────────────────────────────────────
# RETURN REQUEST  (Exchange flow — defective item → exchange code)
# ─────────────────────────────────────────────────────────────────────────────

class ReturnRequest(models.Model):
    """
    Customer reports a defective product.
    Admin approves → ExchangeCode is auto-generated via signal.
    No physical return; no refund. Exchange/upgrade only.
    """
    STATUS_CHOICES = [
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='return_requests'
    )
    # Authenticated user — set from request.user in view
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True,
    )
    # Guest identifier
    guest_email = models.EmailField(blank=True)

    defect_description = models.TextField(
        help_text="Customer describes the product defect in detail"
    )
    defect_video_url = models.URLField(
        max_length=1000, blank=True, null=True,
        help_text="Link to defect video (YouTube, Google Drive, etc.)",
    )
    # Always Exchange — Upgrade option removed
    request_type = models.CharField(max_length=20, default='Exchange')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    admin_notes = models.TextField(
        blank=True,
        help_text="Admin response visible to customer",
    )
    exchange_code = models.OneToOneField(
        ExchangeCode,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='return_request',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
    class Meta:
        verbose_name = "Exchange Request"
        verbose_name_plural = "Exchange Requests"

    def __str__(self):
        return f"ExchangeRequest #{self.id} — Order #{self.order_id} [{self.status}]"


# ─── Signal: auto-create ExchangeCode when ReturnRequest is Approved ─────────

@receiver(post_save, sender=ReturnRequest)
def create_exchange_code_on_approval(sender, instance, created, **kwargs):
    """
    Fires when a ReturnRequest is saved.
    Creates ExchangeCode only when:
      - status just became 'Approved'
      - no exchange_code exists yet

    FIX: Uses ReturnRequest.objects.filter().update() with update_fields to
    avoid triggering another post_save (which would recurse infinitely).
    """
    if instance.status != 'Approved':
        return
    if instance.exchange_code_id:
        return  # Already has a code — do nothing

    # Avoid duplicate codes for the same order
    existing = ExchangeCode.objects.filter(order=instance.order).first()
    if existing:
        # Link existing code without re-triggering signal
        ReturnRequest.objects.filter(pk=instance.pk).update(
            exchange_code=existing,
            approved_at=timezone.now(),
        )
        return

    code = ExchangeCode.objects.create(
        order=instance.order,
        original_order_value=instance.order.subtotal,
        expires_at=timezone.now() + timedelta(days=30),
        notes=f"Auto-generated for exchange request #{instance.pk}",
    )
    # Use .update() to avoid recursive post_save
    ReturnRequest.objects.filter(pk=instance.pk).update(
        exchange_code=code,
        approved_at=timezone.now(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ORDER RETURN REQUEST  (Physical return flow — admin approves → manual refund)
# ─────────────────────────────────────────────────────────────────────────────

class OrderReturnRequest(models.Model):
    """
    Physical return request.
    Customer wants to return the item and get a refund.
    Admin reviews, approves, and triggers refund via admin action.

    stock_restored flag prevents double stock restoration when admin approves.
    approved_at is set by the admin action service.
    """
    STATUS_CHOICES = [
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Completed', 'Completed'),  # Refund processed
    ]

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='order_return_requests'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True,
    )
    guest_email = models.EmailField(blank=True)

    reason = models.TextField(help_text="Reason for return")
    video_url = models.URLField(
        max_length=1000, blank=True, null=True,
        help_text="Optional video evidence",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    admin_notes = models.TextField(blank=True)

    # Set by admin action when processing refund
    refund_initiated = models.BooleanField(default=False)
    razorpay_refund_id = models.CharField(max_length=100, blank=True)

    # Stock restoration guard — set True once stock has been restored for this return
    stock_restored = models.BooleanField(
        default=False,
        help_text="True once stock has been restored for this return. Never set manually.",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ReturnRequest #{self.id} — Order #{self.order_id} [{self.status}]"
