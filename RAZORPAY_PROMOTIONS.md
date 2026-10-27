# Razorpay promotion callback setup

This change adds the two missing promotion callbacks for the Magic Checkout
dashboard. It does **not** replace the storefront's existing Standard Checkout.
It is ready for backend review and deployment, not already live.

## Callback URLs after deployment

The existing public JSON API responds on `admin.rastlina.com`.

| Razorpay field | URL |
| --- | --- |
| URL for get promotions | `https://admin.rastlina.com/api/payments/magic/promotions/` |
| URL for apply promotions | `https://admin.rastlina.com/api/payments/magic/promotions/apply/` |

Both support GET parameters, GET JSON bodies and POST JSON. The `order_id`
must be the opaque `receipt` returned in the corresponding Razorpay order.
New checkout orders store this receipt in `Order.razorpay_receipt` and pass it
to Razorpay. Existing orders without a receipt can use their full opaque
`order_...` Razorpay ID. Sequential local order IDs are not accepted.

Keep both promotions-secret-key switches disabled: these public callbacks
follow Razorpay's documented unauthenticated custom-platform integration.
An unrelated Razorpay API key or payment webhook secret is not a callback URL.

Official callback contract:
https://razorpay.com/docs/payments/magic-checkout/web/

## Behavior

- Coupons remain managed in `/admin/store/coupon/`.
- Eligibility uses the stored order subtotal, never a caller-supplied amount.
- Only unpaid, pending orders linked to a Razorpay order can quote coupons.
- Active dates, usage limits and minimum subtotals are enforced.
- Discounts are returned in integer paise, capped at the item subtotal.
- Existing coupon, exchange or other pre-discounts block additional coupons.
- Responses contain no customer contact or delivery details and are not cached.
- Listing/applying a quote does not consume coupon uses or alter order totals.
- The amount, currency and capture settings for Standard Checkout stay the same;
  only the optional receipt is added to new Razorpay orders.

## Deploy to the existing backend server

The GitHub repository is not an automatic backend deployment. The active Django
checkout previously identified on the server was `/var/www/rastlina/project`,
served by `gunicorn.service`. Confirm that this is still the active checkout.

1. Review and merge the pull request. Back up the production database and source.
2. Deploy this commit using the backend's normal release process. Preserve the
   existing `.env`, database and media files, and any uncommitted live changes.
3. From the active checkout, using the **existing backend virtual environment**:

   ```sh
   python manage.py migrate orders
   python manage.py check
   ```

   Migration `orders.0005_order_razorpay_receipt` adds a nullable unique receipt
   column. It does not overwrite or backfill existing orders.

4. Restart and verify the service:

   ```sh
   systemctl restart gunicorn
   systemctl is-active gunicorn
   ```

5. Confirm the new paths return JSON instead of 404. A GET without an `order_id`
   intentionally returns a `failure_code` and `failure_reason` envelope.
6. Create a new checkout using Razorpay **Test Mode**, without making a live
   purchase. Confirm its Razorpay receipt matches the local order receipt.
   Use that receipt to check coupon listing and a quote; a 10% coupon on an
   INR 500 subtotal must return `promotion.value: 5000`.
7. Enter the verified URLs above in the Razorpay dashboard and save. Enable
   auto-fetch only when you intend to list those eligible admin coupons.
8. Confirm a normal Standard Checkout still creates the expected payable total.

If the release must be rolled back, restore the previous source and restart.
The added nullable receipt column can remain in place; do not drop order data.

## Before activating Magic Checkout on the storefront

These callback URLs alone are not a full Magic Checkout migration. The current
storefront and payment verification expect the original Standard Checkout total.
Do not switch to `magic-checkout.js` or `one_click_checkout` in this release.

A separate end-to-end migration must add line items and shipping callbacks, then
reconcile the **authenticated final Razorpay order** (selected promotions,
shipping, taxes and payable amount) with the local order before capture and
coupon consumption. Client-returned discount values are not payment authority.
Until that is implemented and tested, using a quote to collect a different
payment amount would cause a mismatch with the local order.

Do not enable an abandoned-cart webhook with the payment webhook URL. The
existing signed payment webhook is a different integration.

## Verification performed

```sh
python manage.py test payments.test_magic_promotions store.test_catalogue_performance --settings=core.payment_test_settings
python manage.py makemigrations --check --dry-run --settings=core.payment_test_settings
python manage.py check --settings=core.payment_test_settings
```

Tests run on the repository's Django 5.2.13 and DRF 3.17.1, using SQLite and no
production credentials, live payments, or customer data. Production deployment
and a Razorpay Test Mode round trip still require access to the running backend.
