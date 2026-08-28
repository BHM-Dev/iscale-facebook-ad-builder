from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, JSON, Table, Boolean, Numeric, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

def generate_uuid():
    return str(uuid.uuid4())

def normalize_account_id(acct):
    """Normalize a Meta ad account id to the act_-prefixed form for consistent
    comparison (Meta returns 'act_123'; UI/DB may store either form)."""
    if not acct:
        return acct
    acct = str(acct).strip()
    return acct if acct.startswith("act_") else f"act_{acct}"

# Many-to-Many relationship table for User <-> Role
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', String, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', String, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

# Many-to-Many relationship table for Role <-> Permission
role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', String, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', String, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

# Many-to-Many relationship table for Brand <-> CustomerProfile
brand_profiles = Table(
    'brand_profiles',
    Base.metadata,
    Column('brand_id', String, ForeignKey('brands.id', ondelete='CASCADE'), primary_key=True),
    Column('profile_id', String, ForeignKey('customer_profiles.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roles = relationship("Role", secondary=user_roles, back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    ad_accounts = relationship("UserAdAccount", back_populates="user", cascade="all, delete-orphan")

    def allowed_account_ids(self):
        """Meta ad accounts this user may see/act on.

        Returns None = UNRESTRICTED (superuser, or a user with no explicit
        assignments — the non-breaking default). Otherwise a list of the
        normalized (act_-prefixed) account IDs the user is scoped to.
        """
        if self.is_superuser:
            return None
        ids = [normalize_account_id(a.ad_account_id) for a in self.ad_accounts]
        return ids or None

    def has_permission(self, permission_name: str) -> bool:
        """Check if user has a specific permission through any of their roles"""
        if self.is_superuser:
            return True
        for role in self.roles:
            for permission in role.permissions:
                if permission.name == permission_name:
                    return True
        return False

    def has_role(self, role_name: str) -> bool:
        """Check if user has a specific role"""
        if self.is_superuser:
            return True
        return any(role.name == role_name for role in self.roles)

class UserAdAccount(Base):
    """Per-user Meta ad account allow-list (visibility + action scoping).

    No rows for a user = unrestricted (see User.allowed_account_ids)."""
    __tablename__ = "user_ad_accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ad_account_id = Column(String, nullable=False)  # Meta act_... id
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="ad_accounts")

    __table_args__ = (
        UniqueConstraint('user_id', 'ad_account_id', name='uq_user_ad_account'),
    )


class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, nullable=False)  # e.g., "brands:create", "ads:delete"
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")

class Brand(Base):
    __tablename__ = "brands"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    logo = Column(String, nullable=True)
    primary_color = Column(String, default='#3B82F6')
    secondary_color = Column(String, default='#10B981')
    highlight_color = Column(String, default='#F59E0B')
    voice = Column(Text, nullable=True)
    vertical_id = Column(String, ForeignKey('verticals.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    products = relationship("Product", back_populates="brand", cascade="all, delete-orphan")
    profiles = relationship("CustomerProfile", secondary=brand_profiles, back_populates="brands")
    generated_ads = relationship("GeneratedAd", back_populates="brand")

    @property
    def colors(self):
        return {
            "primary": self.primary_color,
            "secondary": self.secondary_color,
            "highlight": self.highlight_color
        }
    
    @property
    def profileIds(self):
        return [p.id for p in self.profiles]

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=generate_uuid)
    brand_id = Column(String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    product_shots = Column(JSON, nullable=True)
    default_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    brand = relationship("Brand", back_populates="products")

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    demographics = Column(Text, nullable=True)
    pain_points = Column(Text, nullable=True)
    goals = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    brands = relationship("Brand", secondary=brand_profiles, back_populates="profiles")

class FacebookCampaign(Base):
    __tablename__ = "facebook_campaigns"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    objective = Column(String, nullable=False)
    budget_type = Column(String, nullable=False)
    budget_schedule_type = Column(String, nullable=True, default='DAILY')  # 'DAILY' or 'LIFETIME'
    daily_budget = Column(Integer, nullable=True)
    lifetime_budget = Column(Integer, nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    bid_strategy = Column(String, nullable=True)
    special_ad_categories = Column(JSON, nullable=True, default=list)  # e.g. ["HOUSING"] or []
    status = Column(String, default='PAUSED')
    fb_campaign_id = Column(String, nullable=True)
    fb_account_id = Column(String, nullable=True, index=True)  # Meta act_ id this campaign belongs to
    brand_id = Column(String, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    adsets = relationship("FacebookAdSet", back_populates="campaign", cascade="all, delete-orphan")
    brand = relationship("Brand", foreign_keys=[brand_id])

class FacebookAdSet(Base):
    __tablename__ = "facebook_adsets"

    id = Column(String, primary_key=True, default=generate_uuid)
    campaign_id = Column(String, ForeignKey("facebook_campaigns.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    optimization_goal = Column(String, nullable=False)
    budget_schedule_type = Column(String, nullable=True, default='DAILY')  # 'DAILY' or 'LIFETIME'
    daily_budget = Column(Integer, nullable=True)
    lifetime_budget = Column(Integer, nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    bid_strategy = Column(String, nullable=True)
    bid_amount = Column(Integer, nullable=True)
    targeting = Column(JSON, nullable=True)
    pixel_id = Column(String, nullable=True)
    conversion_event = Column(String, nullable=True)
    status = Column(String, default='PAUSED')
    fb_adset_id = Column(String, nullable=True)
    fb_account_id = Column(String, nullable=True, index=True)  # Meta act_ id this adset belongs to
    brand_id = Column(String, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("FacebookCampaign", back_populates="adsets")
    brand = relationship("Brand", foreign_keys=[brand_id])
    ads = relationship("FacebookAd", back_populates="adset", cascade="all, delete-orphan")

class FacebookAd(Base):
    __tablename__ = "facebook_ads"

    id = Column(String, primary_key=True, default=generate_uuid)
    adset_id = Column(String, ForeignKey("facebook_adsets.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    creative_name = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    # Video support fields
    media_type = Column(String, default='image')  # 'image' or 'video'
    video_url = Column(String, nullable=True)
    video_id = Column(String, nullable=True)  # Facebook video ID
    thumbnail_url = Column(String, nullable=True)
    bodies = Column(JSON, nullable=True)
    headlines = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    cta = Column(String, nullable=True)
    website_url = Column(String, nullable=True)
    status = Column(String, default='PAUSED')
    fb_ad_id = Column(String, nullable=True)
    fb_creative_id = Column(String, nullable=True)
    # Bulk Match Import fields. secondary_image_url stores the durable URL of
    # the matched 9x16 asset — it is sent to Meta via create_creative's
    # asset_feed_spec path (Story placement image, alongside the 1x1 Feed
    # image) in facebook_service.py. Not yet confirmed against a live Meta
    # API response — pending live-test verification (see the url_tags
    # comment in create_creative for the same caveat). ad_number traces the
    # row back to the source batch's copy doc (e.g. "AD 12").
    secondary_image_url = Column(String, nullable=True)
    ad_number = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    adset = relationship("FacebookAdSet", back_populates="ads")

class AutoPauseRule(Base):
    """Rule that automatically pauses a Facebook ad set when a performance threshold is breached."""
    __tablename__ = "auto_pause_rules"

    id = Column(String, primary_key=True, default=generate_uuid)
    adset_id = Column(String, ForeignKey("facebook_adsets.id", ondelete="CASCADE"), nullable=False)
    # metric: 'cpl' | 'cpa' | 'ctr'
    metric = Column(String, nullable=False)
    # operator: 'greater_than' | 'less_than'
    operator = Column(String, nullable=False, default='greater_than')
    threshold = Column(Integer, nullable=False)          # e.g. 50 = $50 CPL
    min_spend = Column(Integer, nullable=False, default=20)  # minimum $ spend before rule fires
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    triggered_at = Column(DateTime(timezone=True), nullable=True)
    trigger_reason = Column(String, nullable=True)       # human-readable e.g. "CPL $68 > $50"

    adset = relationship("FacebookAdSet", backref="auto_pause_rules")


class WinningAd(Base):
    __tablename__ = "winning_ads"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    image_url = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    analysis = Column(Text, nullable=True)
    recreation_prompt = Column(Text, nullable=True)
    topic = Column(String, nullable=True)
    mood = Column(String, nullable=True)
    subject_matter = Column(String, nullable=True)
    copy_analysis = Column(Text, nullable=True)
    product_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    design_style = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    structural_analysis = Column(Text, nullable=True)
    layering = Column(Text, nullable=True)
    template_structure = Column(JSON, nullable=True)
    color_palette = Column(JSON, nullable=True)
    typography_system = Column(JSON, nullable=True)
    copy_patterns = Column(JSON, nullable=True)
    visual_elements = Column(JSON, nullable=True)
    template_category = Column(String, nullable=True)
    
    # Ad Remix Engine fields
    blueprint_json = Column(JSON, nullable=True)  # Stores the deconstructed blueprint
    blueprint_analyzed_at = Column(DateTime(timezone=True), nullable=True)  # When blueprint was created
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    generated_ads = relationship("GeneratedAd", back_populates="template")

class GeneratedAd(Base):
    __tablename__ = "generated_ads"

    id = Column(String, primary_key=True, default=generate_uuid)
    brand_id = Column(String, ForeignKey("brands.id", ondelete="SET NULL"), nullable=True)
    product_id = Column(String, ForeignKey("products.id", ondelete="SET NULL"), nullable=True) # Assuming product_id is also FK, though not explicit in original schema it makes sense
    template_id = Column(String, ForeignKey("winning_ads.id", ondelete="SET NULL"), nullable=True)
    image_url = Column(String, nullable=True)  # Changed to nullable for video ads
    headline = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    cta = Column(String, nullable=True)
    size_name = Column(String, nullable=True)
    dimensions = Column(String, nullable=True)
    prompt = Column(Text, nullable=True)
    ad_bundle_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Video support fields
    media_type = Column(String, default='image')  # 'image' or 'video'
    video_url = Column(String, nullable=True)
    video_id = Column(String, nullable=True)  # Facebook video ID
    thumbnail_url = Column(String, nullable=True)
    # Meta ad ID — written back after push. PRIMARY join key to RedTrack sub1 (= Meta ad id).
    fb_ad_id = Column(String, nullable=True, index=True)
    # Attribution rollup keys — written back at push time (not the primary revenue join)
    fb_adset_id = Column(String, nullable=True, index=True)
    fb_campaign_id = Column(String, nullable=True)
    fb_creative_id = Column(String, nullable=True)
    # Learning-loop metadata
    angle = Column(String, nullable=True)          # creative angle used (e.g. "rate_shock")
    source_ad_id = Column(String, nullable=True)   # Meta ad id this was remixed from (provenance)
    profile_id = Column(String, nullable=True)     # audience profile (loose ref, mirrors niche)
    # Performance snapshot — synced from RedTrack sub1 (ad grain) by the perf-sync job
    revenue = Column(Numeric(precision=10, scale=2), nullable=True)
    profit = Column(Numeric(precision=10, scale=2), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    # Text overlay fields — store what was baked into the image so Iterate/Remix can reconstruct settings
    niche = Column(String, nullable=True)
    overlay_enabled = Column(Boolean, default=False, nullable=True)
    overlay_niche_line = Column(String, nullable=True)
    overlay_offer_line = Column(String, nullable=True)
    overlay_cta = Column(String, nullable=True)
    overlay_logo_url = Column(String, nullable=True)

    brand = relationship("Brand", back_populates="generated_ads")
    template = relationship("WinningAd", back_populates="generated_ads")

class Vertical(Base):
    __tablename__ = "verticals"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, unique=True, index=True)  # e.g., "Legal", "Fitness", "E-commerce"
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    saved_searches = relationship("SavedSearch", back_populates="vertical")


class CreativeAngle(Base):
    __tablename__ = "creative_angles"

    id = Column(String, primary_key=True, default=generate_uuid)
    vertical_id = Column(String, ForeignKey('verticals.id', ondelete='CASCADE'), nullable=True)
    name = Column(String, nullable=False)
    hook = Column(String, nullable=True)
    headline = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    vertical = relationship("Vertical")

    __table_args__ = (
        UniqueConstraint('vertical_id', 'name', name='uq_creative_angles_vertical_name'),
    )


class FacebookPage(Base):
    __tablename__ = "facebook_pages"

    id = Column(String, primary_key=True, default=generate_uuid)
    page_name = Column(String, nullable=False, unique=True, index=True)
    page_url = Column(String, nullable=True)
    vertical_id = Column(String, ForeignKey('verticals.id', ondelete='SET NULL'), nullable=True)
    total_ads = Column(Integer, default=0)  # Cached count of ads from this page
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vertical = relationship("Vertical")
    ads = relationship("ScrapedAd", back_populates="facebook_page")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(String, primary_key=True, default=generate_uuid)
    query = Column(String, nullable=False)
    country = Column(String, nullable=True)
    negative_keywords = Column(JSON, nullable=True)  # List of negative keywords
    vertical_id = Column(String, ForeignKey('verticals.id', ondelete='SET NULL'), nullable=True)
    search_type = Column(String, default='one_time')  # 'one_time', 'scheduled_daily', 'scheduled_weekly'
    schedule_config = Column(JSON, nullable=True)  # Cron schedule config for scheduled searches
    is_active = Column(Boolean, default=True)  # For scheduled searches
    last_run = Column(DateTime(timezone=True), nullable=True)
    ads_requested = Column(Integer, nullable=True)  # How many ads were requested (limit)
    ads_returned = Column(Integer, nullable=True)  # How many ads API returned
    ads_new = Column(Integer, nullable=True)  # How many new ads (not duplicates)
    ads_duplicate = Column(Integer, nullable=True)  # How many duplicate ads
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vertical = relationship("Vertical", back_populates="saved_searches")
    ads = relationship("ScrapedAd", back_populates="saved_search", cascade="all, delete-orphan")


class ApiUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    endpoint = Column(String, nullable=False)  # "facebook_ads_library"
    api_calls = Column(Integer, nullable=False)  # Number of API calls made
    ads_returned = Column(Integer, nullable=False)  # Ads returned from API
    ads_saved = Column(Integer, nullable=False)  # Ads saved after filtering
    query = Column(String, nullable=True)  # Search query
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD for daily grouping


class PageBlacklist(Base):
    __tablename__ = "page_blacklist"

    id = Column(String, primary_key=True, default=generate_uuid)
    page_name = Column(String, nullable=False, unique=True, index=True)  # Facebook page name
    reason = Column(String, nullable=True)  # Optional reason for blacklisting
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KeywordBlacklist(Base):
    __tablename__ = "keyword_blacklist"

    id = Column(String, primary_key=True, default=generate_uuid)
    keyword = Column(String, nullable=False, unique=True, index=True)  # Keyword to filter
    reason = Column(String, nullable=True)  # Optional reason for blacklisting
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SearchLog(Base):
    __tablename__ = "search_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    search_query = Column(String, nullable=False)
    country = Column(String, nullable=True)
    negative_keywords = Column(JSON, nullable=True)  # List of keywords excluded
    vertical_id = Column(String, ForeignKey('verticals.id', ondelete='SET NULL'), nullable=True)

    # Metrics
    total_ads_found = Column(Integer, default=0)  # Total ads returned from API
    filtered_by_page_blacklist = Column(Integer, default=0)  # Ads filtered by page blacklist
    filtered_by_keyword_blacklist = Column(Integer, default=0)  # Ads filtered by keyword blacklist
    final_ads_saved = Column(Integer, default=0)  # Final count after all filtering

    # New pages discovered
    new_pages_blacklisted = Column(JSON, nullable=True)  # List of page names added to blacklist during/after search

    # Execution details
    api_calls_made = Column(Integer, default=0)
    search_type = Column(String, nullable=True)  # 'one_time', 'scheduled_daily', 'scheduled_weekly'
    execution_time_seconds = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    date = Column(String, nullable=False, index=True)  # YYYY-MM-DD for daily grouping

    vertical = relationship("Vertical")


class ScrapedAd(Base):
    __tablename__ = "scraped_ads"

    id = Column(String, primary_key=True, default=generate_uuid)
    brand_name = Column(String, nullable=True)  # DEPRECATED: Use facebook_page relationship instead
    headline = Column(String, nullable=True)  # Ad headline
    ad_copy = Column(Text, nullable=True)  # Ad body text
    cta_text = Column(String, nullable=True)
    platform = Column(String, default='facebook')
    external_id = Column(String, nullable=True, unique=True, index=True)  # ID from platform
    content_hash = Column(String, nullable=True, unique=True, index=True)  # Hash of ad content for deduplication
    ad_link = Column(String, nullable=False)  # Link to original ad on FB Ads Library
    platforms = Column(JSON, nullable=True)  # ['facebook', 'instagram'] etc
    start_date = Column(String, nullable=True)  # When ad started running
    media_type = Column(String, nullable=True)  # 'image', 'video', or 'carousel'
    media_url = Column(String, nullable=True)  # Primary image/video thumbnail URL — may expire (Facebook CDN)
    destination_domain = Column(String, nullable=True)  # Landing domain shown in rendered Ad Library card
    source_query = Column(String, nullable=True)  # Chrome/API query that surfaced this ad
    rank_position = Column(Integer, nullable=True)  # Rank in the rendered, sorted capture
    sort_mode = Column(String, nullable=True)  # e.g. total_impressions_desc
    is_multiple_versions = Column(Boolean, default=False, nullable=True)
    video_urls = Column(JSON, nullable=True)  # Observed FB CDN video URLs; may expire
    thumbnail_url = Column(String, nullable=True)
    creative_intel = Column(JSON, nullable=True)  # Capture notes, volume signals, source metadata
    volume_score = Column(Integer, nullable=True)  # Directional score, not spend/impression truth
    first_seen = Column(DateTime(timezone=True), server_default=func.now())  # First time ad was scraped
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())  # Last time ad was seen
    seen_count = Column(Integer, default=1)  # Number of times this ad has been encountered in scrapes
    search_id = Column(String, ForeignKey('saved_searches.id', ondelete='CASCADE'), nullable=True)  # Link to search
    facebook_page_id = Column(String, ForeignKey('facebook_pages.id', ondelete='SET NULL'), nullable=True)
    is_saved = Column(Boolean, default=False, nullable=False, server_default='false')  # User-curated save flag
    angle_tag = Column(String, nullable=True)  # Assigned angle: fear/social_proof/urgency/savings/authority/story/curiosity
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    saved_search = relationship("SavedSearch", back_populates="ads")
    facebook_page = relationship("FacebookPage", back_populates="ads")

class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    variables = Column(JSON, nullable=True)  # List of variable names
    template = Column(Text, nullable=False)  # The actual prompt template
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AdStyle(Base):
    __tablename__ = "ad_styles"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    best_for = Column(JSON, nullable=True)  # List of industries
    visual_layout = Column(String, nullable=True)
    psychology = Column(Text, nullable=True)
    mood = Column(String, nullable=True)
    lighting = Column(String, nullable=True)
    composition = Column(String, nullable=True)
    design_style = Column(String, nullable=True)
    prompt = Column(Text, nullable=True)  # Image generation prompt
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class BrandScrape(Base):
    """Tracks scraping sessions for a specific Facebook page/brand."""
    __tablename__ = "brand_scrapes"

    id = Column(String, primary_key=True, default=generate_uuid)
    brand_name = Column(String, nullable=False, index=True)  # User-defined name, also R2 folder name
    page_id = Column(String, nullable=False)  # FB page ID from URL
    page_name = Column(String, nullable=True)  # Actual FB page name (discovered during scrape)
    page_url = Column(String, nullable=False)  # Original FB Ads Library URL
    total_ads = Column(Integer, default=0)  # Total ads found
    media_downloaded = Column(Integer, default=0)  # Successfully downloaded media count
    status = Column(String, default='pending')  # pending, scraping, completed, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ads = relationship("BrandScrapedAd", back_populates="brand_scrape", cascade="all, delete-orphan")


class BrandScrapedAd(Base):
    """Individual ad scraped from a brand's Facebook page with media stored on R2."""
    __tablename__ = "brand_scraped_ads"

    id = Column(String, primary_key=True, default=generate_uuid)
    brand_scrape_id = Column(String, ForeignKey('brand_scrapes.id', ondelete='CASCADE'), nullable=False)
    external_id = Column(String, nullable=False, index=True)  # FB ad library ID
    page_name = Column(String, nullable=True)  # Facebook page name
    page_link = Column(String, nullable=True)  # Link to page's ads in library
    headline = Column(String, nullable=True)
    ad_copy = Column(Text, nullable=True)
    cta_text = Column(String, nullable=True)
    media_type = Column(String, nullable=True)  # image, video, carousel
    media_urls = Column(JSON, nullable=True)  # R2 URLs for downloaded media
    original_media_urls = Column(JSON, nullable=True)  # Original FB media URLs
    platforms = Column(JSON, nullable=True)  # ['facebook', 'instagram']
    start_date = Column(String, nullable=True)
    ad_link = Column(String, nullable=True)  # FB Ads Library link
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    brand_scrape = relationship("BrandScrape", back_populates="ads")


class AdCopyLibrary(Base):
    """Joel's real winning ad copy — used as few-shot examples in copy generation prompts."""
    __tablename__ = "ad_copy_library"

    id = Column(String, primary_key=True, default=generate_uuid)
    fb_ad_id = Column(String, unique=True, index=True, nullable=False)
    fb_adset_id = Column(String, nullable=True, index=True)
    adset_name = Column(String, nullable=True)            # raw adset name from Meta
    niche = Column(String, nullable=True, index=True)     # extracted from adset name
    headline = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    cta_type = Column(String, nullable=True)
    spend = Column(Numeric(precision=10, scale=2), nullable=True)   # for ranking
    cpl = Column(Numeric(precision=8, scale=2), nullable=True)      # lower = better
    status = Column(String, nullable=True)                # ACTIVE | PAUSED — from Meta at sync time
    is_pinned = Column(Boolean, default=False)            # Joel pins his best examples
    imported_at = Column(DateTime(timezone=True), server_default=func.now())


class RedTrackCache(Base):
    """Cached RedTrack report data per Meta ad set, refreshed every 30 minutes."""
    __tablename__ = "redtrack_cache"

    id = Column(String, primary_key=True, default=generate_uuid)
    fb_adset_id = Column(String, nullable=False, index=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    conversions = Column(Integer, nullable=True)
    revenue = Column(Numeric(precision=10, scale=2), nullable=True)
    cost = Column(Numeric(precision=10, scale=2), nullable=True)
    profit = Column(Numeric(precision=10, scale=2), nullable=True)
    roas = Column(Numeric(precision=6, scale=2), nullable=True)
    cpl = Column(Numeric(precision=8, scale=2), nullable=True)
    clicks = Column(Integer, nullable=True)
    quality_rate = Column(Numeric(precision=4, scale=3), nullable=True)  # rt_conversions / meta_leads
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class PnlCostEntry(Base):
    """A non-media cost line on the P&L: retainers, commissions, tooling, creative credits.

    Ad spend comes from Meta and revenue from RedTrack; everything else that eats
    into net profit is a row in this table.

    `ad_account_id` NULL means the cost spans every account (e.g. Abel's retainer,
    which covers whatever accounts he's working on). Those are split across accounts
    at read time using `allocation_method`.
    """
    __tablename__ = "pnl_cost_entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    # NULL = applies to all ad accounts, split per allocation_method
    ad_account_id = Column(String, nullable=True, index=True)  # normalized act_...
    label = Column(String, nullable=False)
    category = Column(String, nullable=False, default="other")  # labor|tooling|creative|data|other
    cost_type = Column(String, nullable=False, default="one_off")
    # one_off | recurring_monthly | pct_of_spend | pct_of_revenue
    # | pct_of_gross_profit (revenue - spend)
    # | pct_of_profit (revenue - spend - all non-pct_of_profit costs)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)  # dollars, or percent for pct_*
    allocation_method = Column(String, nullable=False, default="by_spend")  # by_spend|even
    effective_from = Column(Date, nullable=False)  # first day of the first month it applies
    effective_to = Column(Date, nullable=True)     # NULL = ongoing
    notes = Column(Text, nullable=True)
    # RESERVED for Phase 2/3 — auto-captured creative platform spend (kie.ai, video gen)
    vendor = Column(String, nullable=True)
    source = Column(String, nullable=False, default="manual")  # manual|auto_kie|auto_video
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # onupdate is SQLAlchemy-side: only ORM/Core writes bump this. A raw SQL
    # UPDATE leaves it stale — don't treat it as a DB-level "last touched".
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PnlMonthSnapshot(Base):
    """Frozen external figures for a CLOSED month, per ad account.

    /pnl/months walked six months of Meta and revenue API calls on every load —
    23s in production. A closed month's ad spend and billable revenue never
    change, so they are fetched once and stored here.

    Deliberately stores ONLY the external data. Costs are not snapshotted: they
    come from pnl_cost_entries, which the user edits, so adding a retainer today
    has to change every past month's net profit. Costs are recomputed from the
    ledger on every read — a local query, effectively free.

    The current month is never snapshotted, and a month whose fetch came back
    incomplete is never snapshotted either — freezing a bad number is worse than
    re-fetching a good one.
    """
    __tablename__ = "pnl_month_snapshots"

    id = Column(String, primary_key=True, default=generate_uuid)
    ad_account_id = Column(String, nullable=False, index=True)  # normalized act_...
    month = Column(Date, nullable=False)  # first day of the month, in the reporting tz
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    spend = Column(Numeric(precision=14, scale=2), nullable=True)
    revenue = Column(Numeric(precision=14, scale=2), nullable=True)
    unattributed_revenue = Column(Numeric(precision=14, scale=2), nullable=True)
    conversions = Column(Integer, nullable=True)
    revenue_source = Column(String, nullable=True)
    unmapped_adsets = Column(Integer, nullable=True)
    event_breakdown = Column(JSON, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())
    synced_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint('ad_account_id', 'month', name='uq_pnl_month_snapshot'),
    )


class DriveAsset(Base):
    """Creative synced from Joel's shared Google Drive folder into R2.

    brand_id is resolved from the top-level folder under the shared Drive root — that's
    the only reliably-structured level. Everything below it (niche/angle, creative-concept
    folders, arbitrary depth) is stored verbatim in folder_path rather than forced into
    columns, since Joel's naming isn't a fixed taxonomy. product_id stays null until a
    person tags it in the library UI; there's no reliable folder-level signal for it today.
    """
    __tablename__ = "drive_assets"

    id = Column(String, primary_key=True, default=generate_uuid)
    drive_file_id = Column(String, unique=True, nullable=False, index=True)
    brand_id = Column(String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    format = Column(String, nullable=False)
    folder_path = Column(String, nullable=True)
    file_name = Column(String, nullable=False)
    # Despite the name, this stores the full public R2 URL (see
    # drive_sync_service._upload_to_r2), not a bare object key — the frontend
    # uses it directly as an <img>/<video> src and as imageUrl/videoUrl. Don't
    # "fix" this to a bare key without also updating every consumer.
    r2_key = Column(String, nullable=False)
    thumbnail_r2_key = Column(String, nullable=True)
    drive_modified_time = Column(DateTime(timezone=True), nullable=False)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived = Column(Boolean, default=False, nullable=False)
    # Reserved for future features, unused in MVP:
    soft_tags = Column(String, nullable=True)
    variant = Column(String, nullable=True)
    geo = Column(String, nullable=True)

    brand = relationship("Brand")
    product = relationship("Product")


class DriveSyncState(Base):
    """Singleton key/value store for the Drive changes.list startPageToken checkpoint."""
    __tablename__ = "drive_sync_state"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CapiQualitySnapshot(Base):
    """Daily snapshot of Meta's Dataset Quality API (Event Match Quality) per pixel.

    One row per (pixel_id, fb_account_id, event_name, snapshot_date). Meta's
    API returns EMQ per event_name with no aggregate/all-events row (confirmed
    against Meta's live documented example, 2026-08-28) — so we store every
    event rather than arbitrarily picking one to call "the" score. The
    Dashboard picks which event to headline (e.g. highest composite_score, or
    the account's actual conversion_event) at read time.

    Lets us compare CAPI match quality across ad accounts over time — e.g. an
    advertiser-run CAPI integration (RHO 4) vs. Everflow's CAPI on the other
    accounts. Two caveats that affect whether the comparison is even valid:

    1. EMQ is a property of the pixel/dataset, not the ad account. If two ad
       accounts ever share one Meta pixel, this table can't distinguish them —
       Meta reports the identical score for both. Confirm RHO 4 actually sends
       to a different pixel/dataset before trusting a difference here.
    2. A shared/advertiser-owned pixel may not have granted our token
       dataset-level "Use events dataset" access even if we can manage the ad
       account — check `fetch_error` before assuming null metrics mean "bad
       match quality" rather than "we can't see this pixel yet."

    `pixel_id` is Meta's `dataset_id` in their API naming. `fb_account_id` and
    `account_name` are denormalized at snapshot time so history reads correctly
    even if an account's pixel gets reassigned later. `match_key_feedback` is
    normalized at write time from Meta's `[{identifier, coverage:{percentage}}]`
    array into a flat `{identifier: percentage}` dict for easier rendering.
    `event_coverage` is documented as a trailing 7-day average, not same-day.
    """
    __tablename__ = "capi_quality_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "pixel_id", "fb_account_id", "event_name", "snapshot_date",
            name="uq_capi_quality_pixel_account_event_date",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    pixel_id = Column(String, nullable=False, index=True)
    pixel_name = Column(String, nullable=True)  # e.g. "Commercial Insurance - CAPI" — lets the UI
    # show which pixel an account is on, so two accounts sharing one pixel (confirmed to happen
    # here — RHO's own account has a few ad sets pointed at RHO 4's pixel) is visible, not silently
    # confusing when their EMQ numbers turn out identical.
    fb_account_id = Column(String, nullable=True, index=True)  # normalized act_...
    account_name = Column(String, nullable=True)
    event_name = Column(String, nullable=True)  # Meta's per-event key (e.g. "Lead"); null = fetch-error placeholder row
    snapshot_date = Column(Date, nullable=False, index=True)
    event_match_quality = Column(Numeric(precision=4, scale=2), nullable=True)  # Meta's 0-10 EMQ composite_score
    acr = Column(Numeric(precision=6, scale=2), nullable=True)  # % lift from CAPI vs pixel-only (shape not first-party confirmed)
    event_coverage = Column(Numeric(precision=6, scale=2), nullable=True)  # trailing 7-day avg % (shape not first-party confirmed)
    data_freshness = Column(String, nullable=True)  # e.g. real_time | hourly (shape not first-party confirmed)
    match_key_feedback = Column(JSON, nullable=True)  # normalized {"email": 82.1, ...}
    diagnostics = Column(JSON, nullable=True)  # Meta's raw row, unmodified, for later per-event UI/debugging
    fetch_error = Column(Text, nullable=True)  # set instead of the metrics above when the API call failed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
