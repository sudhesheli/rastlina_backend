import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from orders.models import Order
from orders.views import CheckoutView
from store.models import Category, Coupon, MainCategory, Product
from .razorpay_client import create_order


class MagicPromotionTests(TestCase):
    list_url = '/magic/promotions/'
    apply_url = '/magic/promotions/apply/'

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.order = Order.objects.create(
            subtotal='500.00', total_amount='500.00',
            razorpay_order_id='order_opaque123',
            razorpay_receipt='rst_0123456789abcdef0123456789abcdef',
            shipping_address='Private address', email='private@example.com',
        )
        self.now = timezone.now()
        self.coupon = self.make_coupon('SAVE10', value='10', discount_type='percentage')

    def make_coupon(self, code, **overrides):
        data = dict(
            code=code, value='50.00', discount_type='fixed',
            active=True, min_order_value='100.00', usage_limit=10, uses_count=0,
            valid_from=self.now - timedelta(days=1),
            valid_to=self.now + timedelta(days=1),
        )
        data.update(overrides)
        return Coupon.objects.create(**data)

    def params(self, **overrides):
        return dict(order_id=self.order.razorpay_receipt, **overrides)

    def apply(self, code='SAVE10', **extra):
        return self.client.get(self.apply_url, self.params(code=code, **extra))

    def test_listing_contract_excludes_private_order_information(self):
        response = self.client.get(self.list_url, self.params())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response.data, {'promotions': [{
            'code': 'SAVE10', 'summary': '10% off',
            'description': '10% off on a minimum item subtotal of INR 100.00.',
        }]})
        self.assertNotIn('Private address', response.content.decode())
        self.assertNotIn('private@example.com', response.content.decode())

    def test_percentage_is_calculated_from_server_subtotal_in_paise(self):
        response = self.apply(order_total='999999', subtotal='999999', value=1)
        self.assertEqual(response.data['promotion']['value'], 5000)
        self.assertEqual(response.data['promotion']['value_type'], 'fixed_amount')
        self.assertEqual(response.data['promotion']['type'], 'coupon')

    def test_fractional_percentage_rounds_to_a_whole_paise(self):
        self.order.subtotal = Decimal('123.45')
        self.order.save(update_fields=['subtotal'])
        self.coupon.value = Decimal('12.50')
        self.coupon.min_order_value = 0
        self.coupon.save()
        self.assertEqual(self.apply().data['promotion']['value'], 1543)

    def test_fixed_discount_cannot_exceed_subtotal(self):
        self.make_coupon('BIG', value='5000')
        self.assertEqual(self.apply('BIG').data['promotion']['value'], 50000)

    def test_percentage_cannot_exceed_subtotal(self):
        self.coupon.value = 150
        self.coupon.save()
        self.assertEqual(self.apply().data['promotion']['value'], 50000)

    def test_ineligible_coupons_are_not_listed_or_applied(self):
        cases = [
            {'active': False}, {'valid_to': self.now - timedelta(seconds=1)},
            {'valid_from': self.now + timedelta(days=1)},
            {'uses_count': 10}, {'min_order_value': '500.01'},
            {'value': '0'}, {'value': '-1'}, {'discount_type': 'unknown'},
        ]
        for index, overrides in enumerate(cases):
            with self.subTest(overrides=overrides):
                code = f'INVALID{index}'
                self.make_coupon(code, **overrides)
                listed = self.client.get(self.list_url, self.params()).data['promotions']
                self.assertNotIn(code, [p['code'] for p in listed])
                self.assertIn('failure_code', self.apply(code).data)

    def test_get_json_and_post_json_both_follow_the_contract(self):
        payload = self.params(code='SAVE10')
        get = self.client.generic('GET', self.apply_url, json.dumps(payload), content_type='application/json')
        post = self.client.post(self.apply_url, payload, format='json')
        self.assertEqual(get.status_code, 200)
        self.assertEqual(post.status_code, 200)
        self.assertEqual(get.data, post.data)
        self.assertEqual(post.data['promotion']['value'], 5000)

    def test_callback_does_not_consume_coupon_or_change_order_totals(self):
        for _ in range(2):
            self.assertIn('promotion', self.apply().data)
        self.coupon.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.coupon.uses_count, 0)
        self.assertEqual(self.order.total_amount, Decimal('500.00'))
        self.assertEqual(self.order.discount_amount, 0)
        self.assertFalse(self.order.coupon_applied)
        self.assertEqual(self.order.coupon_code, '')

    def test_prediscounts_are_not_applied_twice(self):
        for field, value in [('discount_amount', Decimal('10')), ('coupon_code', 'SAVE10'), ('exchange_code_used', 'RST-EXCHANGE')]:
            with self.subTest(field=field):
                setattr(self.order, field, value)
                self.order.save(update_fields=[field])
                self.assertEqual(self.client.get(self.list_url, self.params()).data, {'promotions': []})
                self.assertIn('failure_code', self.apply().data)
                setattr(self.order, field, '' if isinstance(value, str) else Decimal('0'))
                self.order.save(update_fields=[field])

    def test_missing_unknown_and_numeric_order_ids_fail_closed(self):
        for params in [{}, {'order_id': str(self.order.pk)}, {'order_id': 'rst_unknown'}, {'order_id': ['bad', 'shape']}]:
            with self.subTest(params=params):
                response = self.client.get(self.list_url, params)
                self.assertNotIn('promotions', response.data)
                self.assertIn('failure_code', response.data)

    def test_paid_cancelled_and_gatewayless_orders_cannot_get_discounts(self):
        for field, value in [('payment_status', 'Paid'), ('order_status', 'Cancelled'), ('razorpay_order_id', None)]:
            with self.subTest(field=field):
                original = getattr(self.order, field)
                setattr(self.order, field, value)
                self.order.save(update_fields=[field])
                self.assertIn('failure_code', self.apply().data)
                setattr(self.order, field, original)
                self.order.save(update_fields=[field])

    def test_legacy_orders_use_opaque_razorpay_ids_without_backfill(self):
        self.order.razorpay_receipt = None
        self.order.save(update_fields=['razorpay_receipt'])
        response = self.client.get(self.list_url, {'order_id': self.order.razorpay_order_id})
        self.assertEqual(response.data['promotions'][0]['code'], 'SAVE10')
        Order.objects.create(total_amount=1, shipping_address='', razorpay_receipt=None)

    def test_missing_and_invalid_coupon_codes_have_failure_envelopes(self):
        for code in ['', 'NOTREAL']:
            with self.subTest(code=code):
                self.assertEqual(self.apply(code).data['failure_code'], 'INVALID_PROMOTION')

    def test_minimum_subtotal_is_inclusive_and_code_is_normalized(self):
        self.coupon.min_order_value = 500
        self.coupon.save()
        self.assertEqual(self.apply(' save10 ').data['promotion']['value'], 5000)

    @patch('payments.razorpay_client._get_client')
    def test_payment_wrapper_retains_standard_payload_and_passes_receipt(self, client):
        client.return_value.order.create.return_value = {'id': 'order_test'}
        create_order(Decimal('123.45'))
        client.return_value.order.create.assert_called_with({'amount': 12345, 'currency': 'INR', 'payment_capture': 1})
        create_order(Decimal('123.45'), receipt=self.order.razorpay_receipt)
        client.return_value.order.create.assert_called_with({'amount': 12345, 'currency': 'INR', 'payment_capture': 1, 'receipt': self.order.razorpay_receipt})

    @patch('payments.razorpay_client.create_order')
    def test_standard_checkout_records_receipt_without_changing_payable_total(self, gateway):
        main = MainCategory.objects.create(name='Plants', slug='plants')
        category = Category.objects.create(name='Indoor', slug='indoor', main_category=main)
        product = Product.objects.create(name='Test plant', slug='test-plant', sku='TEST', category=category, price='199.00', original_price='299.00')
        gateway.return_value = {'id': 'order_new', 'amount': 19900, 'currency': 'INR'}
        request = APIRequestFactory().post('/checkout/', {
            'items': [{'product_id': product.pk, 'quantity': 1}],
            'address': '123 Test Street', 'city': 'Chennai', 'state': 'Tamil Nadu', 'zip_code': '600001',
        }, format='json')
        response = CheckoutView.as_view()(request)
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(razorpay_order_id='order_new')
        self.assertTrue(order.razorpay_receipt.startswith('rst_'))
        self.assertLessEqual(len(order.razorpay_receipt), 40)
        self.assertEqual(order.total_amount, Decimal('199.00'))
        gateway.assert_called_once_with(Decimal('199.00'), receipt=order.razorpay_receipt)
