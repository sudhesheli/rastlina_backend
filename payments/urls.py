"""
payments/urls.py
Mount under /api/payments/ in your root urls.py:
    path('api/payments/', include('payments.urls')),
"""

from django.urls import path

from .views import RazorpayWebhookView, VerifyPaymentView
from .magic_promotions import GetPromotionsView, ApplyPromotionView

urlpatterns = [
    path('magic/promotions/', GetPromotionsView.as_view(), name='magic-promotions'),
    path('magic/promotions/apply/', ApplyPromotionView.as_view(), name='magic-apply-promotion'),
    path('verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('webhook/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
]
