"""Razorpay Magic Checkout promotion callbacks, backed by admin coupons.

Contract: https://razorpay.com/docs/payments/magic-checkout/web/
The apply callback quotes a discount; it does not charge, mark an order paid,
change its financials, or consume coupon uses. These callbacks do not switch
the storefront from Standard Checkout to Magic Checkout.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import F, Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from store.models import Coupon


class PromotionRequestSerializer(serializers.Serializer):
    order_id = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=50, required=False)


def _pending_order(token):
    # Receipts are random, unguessable references, not sequential database IDs.
    # Also accept a full Razorpay ID for existing orders without a receipt.
    if not token.startswith(('rst_', 'order_')):
        return None
    return (
        Order.objects.filter(
            Q(razorpay_receipt=token) | Q(razorpay_order_id=token),
            payment_status='Pending', order_status='Pending',
        )
        .exclude(razorpay_order_id__isnull=True)
        .exclude(razorpay_order_id='')
        .only('subtotal', 'discount_amount', 'coupon_code', 'exchange_code_used')
        .first()
    )


def _has_prediscount(order):
    return bool(order.discount_amount or order.coupon_code or order.exchange_code_used)


def _eligible_coupons(order):
    now = timezone.now()
    return Coupon.objects.filter(
        active=True, valid_from__lte=now, valid_to__gte=now,
        uses_count__lt=F('usage_limit'), min_order_value__lte=order.subtotal,
        value__gt=0, discount_type__in=['fixed', 'percentage'],
    ).order_by('min_order_value', 'code')


def _discount(order, coupon):
    subtotal = max(order.subtotal, Decimal('0'))
    value = coupon.value
    if coupon.discount_type == 'percentage':
        value = subtotal * value / Decimal('100')
    return min(subtotal, max(value, Decimal('0'))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )


def _summary(coupon):
    value = format(coupon.value.normalize(), 'f')
    return f'{value}% off' if coupon.discount_type == 'percentage' else f'INR {value} off'


def _description(coupon):
    minimum = format(coupon.min_order_value, '.2f')
    return f'{_summary(coupon)} on a minimum item subtotal of INR {minimum}.'


def _failure(message, code='REQUIREMENT_NOT_MET'):
    # Razorpay's documented failure envelope is a normal API response.
    return Response({'failure_code': code, 'failure_reason': message})


class PromotionCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response

    def get(self, request):
        return self.handle(request)

    def post(self, request):
        return self.handle(request)

    def validated_order(self, request):
        # Support documented GET parameters, GET JSON bodies, and POST JSON.
        payload = request.query_params or request.data
        serializer = PromotionRequestSerializer(data=payload)
        if not serializer.is_valid():
            return None, None, _failure('A valid order_id is required.')
        order = _pending_order(serializer.validated_data['order_id'])
        if order is None:
            return None, None, _failure('The checkout order is unavailable.')
        return order, serializer.validated_data, None


class GetPromotionsView(PromotionCallbackView):
    def handle(self, request):
        order, data, error = self.validated_order(request)
        if error is not None:
            return error
        if _has_prediscount(order):
            return Response({'promotions': []})
        return Response({'promotions': [
            {'code': coupon.code, 'summary': _summary(coupon),
             'description': _description(coupon)}
            for coupon in _eligible_coupons(order)
            if _discount(order, coupon) > 0
        ]})


class ApplyPromotionView(PromotionCallbackView):
    def handle(self, request):
        order, data, error = self.validated_order(request)
        if error is not None:
            return error
        code = data.get('code', '').strip().upper()
        if not code:
            return _failure('A coupon code is required.', 'INVALID_PROMOTION')
        if _has_prediscount(order):
            return _failure('An existing discount cannot be combined with another coupon.')
        coupon = _eligible_coupons(order).filter(code=code).first()
        if coupon is None:
            return _failure('This coupon is invalid or unavailable for this order.', 'INVALID_PROMOTION')
        paise = int(_discount(order, coupon) * 100)
        if paise <= 0:
            return _failure('This coupon provides no discount for this order.')
        return Response({'promotion': {
            'reference_id': f'coupon_{coupon.pk}',
            'type': 'coupon', 'code': coupon.code, 'value': paise,
            'value_type': 'fixed_amount', 'description': _description(coupon),
        }})
