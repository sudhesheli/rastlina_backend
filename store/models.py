"""
store/models.py — Updated
Additions:
  - Product.temperature: ideal temperature range (care guide)
  - Product.growth_rate: how fast the plant grows (care guide)
  - Product.plant_type: decorative/functional/flowering etc. for non-plant categories use blank
  - SizeOption now also exposed via navbar API for dynamic "Shop by Size"
  - ProductImage popup fix: color dropdown now scoped properly
"""

from django.db import models
from django.core.validators import FileExtensionValidator
from .validators import validate_mp4_upload
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

class MainCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(max_length=50, blank=True,
        help_text="Lucide icon name e.g. 'leaf', 'flower', 'sprout'")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Main Category (Navbar)"
        verbose_name_plural = "Main Categories (Navbar)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class HeroSlide(models.Model):
    image = models.ImageField(upload_to='hero_slides/')
    title = models.CharField(max_length=200, blank=True,
        help_text="Overlay text e.g. 'Self Watering Pots'")
    subtitle = models.CharField(max_length=200, blank=True)
    link_url = models.CharField(max_length=255, blank=True,
        help_text="Internal link e.g. /shop?collection=self-watering")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Hero Slide (Navbar Banner)"
        verbose_name_plural = "Hero Slides (Navbar Banner)"

    def __str__(self):
        return self.title or f"Slide {self.order}"


class Category(models.Model):
    main_category = models.ForeignKey(
        MainCategory, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    description = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False,
        help_text="Show in 'Explore by Category' on homepage")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.main_category.name} \u203a {self.name}"


class SpaceTag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(max_length=100, blank=True,
        help_text="Lucide icon name e.g. 'sofa', 'bed', 'sun'")
    image = models.ImageField(upload_to='spaces/', null=True, blank=True)
    is_featured = models.BooleanField(default=False,
        help_text="Show in 'Curate your atmosphere' on homepage")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# SIZE OPTION
# ─────────────────────────────────────────────────────────────────────────────

class SizeOption(models.Model):
    """
    Admin adds sizes here. Variants pick from this dropdown.
    Examples: Small | Medium | Large | Extra Large | 250ml | Standard
    These are also exposed in the navbar for "Shop by Size".
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Size label shown on website e.g. 'Small', '250ml', 'Standard'"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in dropdowns and on product page"
    )
    show_in_navbar = models.BooleanField(
        default=True,
        help_text="Show this size in the 'Shop by Size' section of the navbar"
    )

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Size Option"
        verbose_name_plural = "Size Options"

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# COLOR OPTION
# ─────────────────────────────────────────────────────────────────────────────

class ColorOption(models.Model):
    """
    Admin adds colors here. Variants AND images pick from this.
    Examples: Terracotta (#C87941) | Sage Green (#8FAF6E) | Matte Black (#1A1A1A)
    """
    name = models.CharField(
        max_length=100, unique=True,
        help_text="Color name shown on website e.g. 'Terracotta', 'Sage Green'"
    )
    hex_code = models.CharField(
        max_length=7, blank=True,
        help_text="Hex color code e.g. #E07B54 \u2014 shown as color dot on product page"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Color Option"
        verbose_name_plural = "Color Options"

    def __str__(self):
        return f"{self.name}" + (f" ({self.hex_code})" if self.hex_code else "")


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT
# ─────────────────────────────────────────────────────────────────────────────

class Product(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    sku = models.CharField(max_length=50, unique=True,
        help_text="e.g. PLT-001, PLN-002")
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name='products')
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='products')
    space_tags = models.ManyToManyField(
        SpaceTag, blank=True, related_name='products')

    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="MRP / crossed-out price")

    # ── Plant Care Details ──────────────────────────────────────────────────
    care_level = models.CharField(max_length=50, blank=True,
        choices=[('easy', 'Easy Care'), ('moderate', 'Moderate'), ('expert', 'Expert')])
    sunlight = models.CharField(max_length=100, blank=True,
        help_text="e.g. 'Bright indirect light'")
    watering = models.CharField(max_length=100, blank=True,
        help_text="e.g. 'Once a week'")
    temperature = models.CharField(
        max_length=100, blank=True,
        help_text="Ideal temperature range e.g. '18\xb0C \u2013 30\xb0C' \u2014 shown in care guide"
    )
    growth_rate = models.CharField(
        max_length=100, blank=True,
        choices=[
            ('slow', 'Slow'),
            ('moderate', 'Moderate'),
            ('fast', 'Fast'),
        ],
        help_text="How fast the plant grows \u2014 shown in care guide"
    )
    pet_friendly = models.BooleanField(null=True, blank=True)
    air_purifying = models.BooleanField(default=False)

    # Content
    description = models.TextField(blank=True)
    care_instructions = models.TextField(
        blank=True,
        help_text="Detailed care guide \u2014 one tip per line. Shown in 'Care Guide' tab on product page.")
    what_you_get = models.TextField(
        blank=True,
        help_text="What's included \u2014 one item per line\ne.g.:\n1 healthy plant\nEco-friendly packaging\nCare card")

    # Homepage toggles
    is_new_arrival = models.BooleanField(default=False)
    is_best_seller = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    is_best_deal = models.BooleanField(default=False,
        help_text="\u2705 Tick to show in Golden Deals / Offers section")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sku} \u2014 {self.name}"

    @property
    def main_category(self):
        return self.category.main_category

    @property
    def primary_image_url(self):
        img = self.images.filter(is_primary=True).first() or self.images.first()
        return img.image.url if img else None


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY ESTIMATE
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryEstimate(models.Model):
    """
    Each product can have multiple delivery rows.
    Within Telangana  →  3-5 business days
    Other States      →  5-7 business days
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='delivery_estimates')
    region = models.CharField(
        max_length=100,
        help_text="e.g. 'Within Telangana', 'Other States', 'North East India'"
    )
    estimate = models.CharField(
        max_length=100,
        help_text="e.g. '3-5 business days', 'Same day'"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.product.sku} | {self.region}: {self.estimate}"


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT VARIANT
# ─────────────────────────────────────────────────────────────────────────────

class ProductVariant(models.Model):
    """
    Each variant = one Size + Color combination.
    Color images are linked via ProductImage.color (not here).
    price_override: extra ₹ on top of base product price.
    stock: 0 = out of stock → frontend blocks add-to-cart and shows OOS banner.
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='variants')
    size = models.ForeignKey(
        SizeOption, on_delete=models.PROTECT, related_name='variants',
        help_text="Pick a size \u2014 add new sizes in 'Size Options' panel")
    color = models.ForeignKey(
        ColorOption, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='variants',
        help_text="Pick a color \u2014 leave blank if no color variant. Add colors in 'Color Options' panel")
    stock = models.PositiveIntegerField(default=0)
    price_override = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00,
        help_text="Extra \u20b9 added to base price. Enter 0 for no change.")

    class Meta:
        unique_together = ('product', 'size', 'color')
        ordering = ['size__order', 'color__order']

    def __str__(self):
        color_str = f" / {self.color.name}" if self.color else ""
        return f"{self.product.sku} | {self.size.name}{color_str} (stock: {self.stock})"

    @property
    def final_price(self):
        return float(self.product.price) + float(self.price_override)

    @property
    def final_original_price(self):
        if self.product.original_price:
            return float(self.product.original_price) + float(self.price_override)
        return None

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def size_name(self):
        return self.size.name

    @property
    def color_name(self):
        return self.color.name if self.color else ""

    @property
    def color_hex(self):
        return self.color.hex_code if self.color else ""


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT IMAGE — Linked to ColorOption directly (cleaner than variant FK)
# ─────────────────────────────────────────────────────────────────────────────

class ProductImage(models.Model):
    """
    Multiple images per product.
    Link to a ColorOption so the right images show when that color is selected.
    Leave color blank for generic/lifestyle images shown regardless of color choice.
    """
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='images')
    color = models.ForeignKey(
        ColorOption, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='product_images',
        help_text=(
            "(Optional) Which color does this image belong to? "
            "When the customer selects this color, these images will be shown first. "
            "Leave blank for images that apply to all colors."
        )
    )
    image = models.ImageField(upload_to='products/')
    alt_text = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(
    default=False,
    help_text="Featured image. Multiple images can be marked as primary."
)
    order = models.PositiveIntegerField(default=0,
        help_text="Display order \u2014 lower number = shown first")

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        color_str = f" [{self.color.name}]" if self.color else ""
        return f"{'[PRIMARY] ' if self.is_primary else ''}Image for {self.product.sku}{color_str}"


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW
# ─────────────────────────────────────────────────────────────────────────────

class Review(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviews')
    user_name = models.CharField(max_length=100)
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField()
    variant_info = models.CharField(max_length=200, blank=True,
        help_text="e.g. 'Medium / Terracotta Pot'")
    is_verified_purchase = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False,
        help_text="Show on homepage testimonials section")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_name} \u2014 {self.product.name} ({self.rating}\u2605)"


# ─────────────────────────────────────────────────────────────────────────────
# FAQ
# ─────────────────────────────────────────────────────────────────────────────

class FAQ(models.Model):
    question = models.CharField(max_length=300)
    answer = models.TextField()
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question[:80]


# ─────────────────────────────────────────────────────────────────────────────
# WATCH AND SHOP
# ─────────────────────────────────────────────────────────────────────────────
class WatchAndShop(models.Model):
    title = models.CharField(max_length=200)

    slug = models.SlugField(unique=True, blank=True)

    # Retained in the database for migration compatibility; hidden from the admin.
    video_url = models.URLField(blank=True, default="", help_text="Legacy video URL (unused).")
    video_file = models.FileField(
        upload_to="watch_shop/videos/", blank=True,
        validators=[FileExtensionValidator(["mp4"]), validate_mp4_upload],
        help_text="Upload an H.264 MP4, ideally under 5 MB (maximum 20 MB).",
    )

    thumbnail = models.ImageField(
        upload_to="watch_shop/", blank=True,
        help_text="Optional preview image. Uses the product image when left blank.",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='watch_videos'
    )

    order = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Watch & Shop Video"
        verbose_name_plural = "Watch & Shop Videos"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)

        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        errors = {}
        if self.is_active:
            if not self.video_file:
                errors["video_file"] = "Upload an MP4 before activating this video."
            if not self.product_id:
                errors["product"] = "Choose the product for the Shop Now button."
            elif not self.product.is_active:
                errors["product"] = "Choose an active product for Shop Now."
            if WatchAndShop.objects.filter(is_active=True).exclude(pk=self.pk).count() >= 4:
                errors["is_active"] = "Maximum 4 active Watch & Shop videos allowed."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title

# ─────────────────────────────────────────────────────────────────────────────
# SITE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class SiteConfig(models.Model):
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    free_shipping_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=999.00)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    whatsapp_number = models.CharField(max_length=20, default='919XXXXXXXXXX',
        help_text="Include country code, no + e.g. 919876543210")
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        verbose_name = "Site Configuration"
        verbose_name_plural = "Site Configuration"

    def __str__(self):
        return "Site Configuration"


# ─────────────────────────────────────────────────────────────────────────────
# COUPON
# ─────────────────────────────────────────────────────────────────────────────

class Coupon(models.Model):
    DISCOUNT_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ]
    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_CHOICES)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    active = models.BooleanField(default=True)
    usage_limit = models.IntegerField(default=100)
    uses_count = models.IntegerField(default=0)

    def is_valid(self):
        now = timezone.now()
        return (
            self.active and
            self.valid_from <= now <= self.valid_to and
            self.uses_count < self.usage_limit
        )

    def __str__(self):
        return f"{self.code} ({self.discount_type} \u2014 {self.value})"

