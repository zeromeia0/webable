from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(120), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    enable_iefp_mode = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    databases = relationship("DatabaseInstance", back_populates="owner", cascade="all, delete-orphan")
    bank_statements = relationship("BankStatement", back_populates="owner_user", cascade="all, delete-orphan")
    audit_logs = relationship("FinanceAuditLog", back_populates="user")
    wishlist_items = relationship("WishlistItem", back_populates="owner", cascade="all, delete-orphan")
    notes = relationship("UserNote", back_populates="owner", cascade="all, delete-orphan")


class DatabaseInstance(Base):
    __tablename__ = "database_instances"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    mode = Column(String(40), default="general", nullable=False)
    finance_db_path = Column(String(255), nullable=False)
    logic_db_path = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    health_status = Column(String(30), default="healthy", nullable=False)
    last_sync_status = Column(String(120), default="Waiting for execution", nullable=False)
    last_activity_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="databases")
    jobs = relationship("JobRun", back_populates="instance", cascade="all, delete-orphan")
    bank_statements = relationship("BankStatement", back_populates="instance", cascade="all, delete-orphan")
    category_budgets = relationship("CategoryBudget", back_populates="instance", cascade="all, delete-orphan")
    monthly_snapshots = relationship("MonthlySnapshot", back_populates="instance", cascade="all, delete-orphan")


class JobRun(Base):
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=False, index=True)
    job_type = Column(String(80), nullable=False)
    status = Column(String(20), default="running", nullable=False)
    logs = Column(Text, default="", nullable=False)
    friendly_message = Column(String(255), default="", nullable=False)
    technical_logs = Column(Text, default="", nullable=False)
    metrics_json = Column(Text, default="{}", nullable=False)
    duration_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    instance = relationship("DatabaseInstance", back_populates="jobs")


class MotherInsightEvent(Base):
    __tablename__ = "mother_insight_events"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False)
    severity = Column(String(20), default="info", nullable=False)
    title = Column(String(160), nullable=False)
    details = Column(Text, default="", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(120), nullable=False)
    statement_month = Column(String(7), nullable=False, index=True)
    bank_name = Column(String(120), nullable=True)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    storage_rel_path = Column(String(512), nullable=False)
    text_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instance = relationship("DatabaseInstance", back_populates="bank_statements")
    owner_user = relationship("User", back_populates="bank_statements")


class MarketQuote(Base):
    __tablename__ = "market_quotes"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    label = Column(String(120), nullable=False)
    price_eur = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    price_usd = Column(Float, nullable=True)
    meta_json = Column(Text, default="{}", nullable=False)
    fetched_at = Column(DateTime, nullable=True)
    fetch_error = Column(Text, nullable=True)


class MarketChartCache(Base):
    """Cached OHLC-style time series for Market Watch charts (per symbol + range)."""

    __tablename__ = "market_chart_cache"
    __table_args__ = (
        UniqueConstraint("symbol", "range_key", name="uq_market_chart_symbol_range"),
        Index("ix_market_chart_fetched", "fetched_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    range_key = Column(String(12), nullable=False, index=True)
    points_json = Column(Text, default="[]", nullable=False)
    fetched_at = Column(DateTime, nullable=True)
    fetch_error = Column(Text, nullable=True)


class CategoryBudget(Base):
    __tablename__ = "category_budgets"
    __table_args__ = (UniqueConstraint("instance_id", "category", name="uq_budget_instance_category"),)

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=False, index=True)
    category = Column(String(80), nullable=False)
    monthly_limit_eur = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instance = relationship("DatabaseInstance", back_populates="category_budgets")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    price_eur = Column(Float, nullable=False, default=0.0)
    priority = Column(String(20), default="medium", nullable=False)
    deadline = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="wishlist_items")


class UserNote(Base):
    __tablename__ = "user_notes"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="notes")


class MonthlySnapshot(Base):
    __tablename__ = "monthly_snapshots"
    __table_args__ = (UniqueConstraint("instance_id", "year", "month", name="uq_snapshot_instance_ym"),)

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    total_income = Column(Float, nullable=False, default=0.0)
    total_expenses = Column(Float, nullable=False, default=0.0)
    net_balance = Column(Float, nullable=False, default=0.0)
    average_monthly_balance = Column(Float, nullable=True)
    safe_to_spend = Column(Float, nullable=True)
    fixed_expenses_total = Column(Float, nullable=False, default=0.0)
    fixed_expenses_percent_income = Column(String(16), nullable=True)
    top_expenses_json = Column(Text, default="[]", nullable=False)
    top_income_json = Column(Text, default="[]", nullable=False)
    comparison_json = Column(Text, default="{}", nullable=False)
    summary_json = Column(Text, default="[]", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instance = relationship("DatabaseInstance", back_populates="monthly_snapshots")


class FinanceAuditLog(Base):
    __tablename__ = "finance_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("database_instances.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String(40), nullable=False)
    details = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="audit_logs")
