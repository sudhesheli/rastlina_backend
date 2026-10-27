"""Payment adapter tests without production credentials or external services."""
from .test_settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, 'orders', 'payments']  # noqa: F405
ROOT_URLCONF = 'payments.urls'
RAZORPAY_KEY_ID = 'test-key-not-for-payments'
