"""Application data only: no synthetic model interactions or copied embeddings."""
from datetime import date,datetime, timezone
import uuid

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():return str(uuid.uuid4())
def now():return datetime.now(timezone.utc)


class Base(DeclarativeBase):pass


class SchemaInfo(Base):
    __tablename__='schema_info'
    id:Mapped[int]=mapped_column(primary_key=True)
    version:Mapped[int]=mapped_column(nullable=False)


class User(Base):
    __tablename__='users'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    email:Mapped[str]=mapped_column(String(254),unique=True,nullable=False)
    display_name:Mapped[str]=mapped_column(String(80),nullable=False)
    password_hash:Mapped[str]=mapped_column(Text,nullable=False)
    bio:Mapped[str]=mapped_column(String(500),default='',nullable=False)
    token_version:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)


class TravelGroup(Base):
    __tablename__='travel_groups'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name:Mapped[str]=mapped_column(String(100),nullable=False)
    owner_id:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
    invite_digest:Mapped[str]=mapped_column(String(64),unique=True,nullable=False)
    revision:Mapped[int]=mapped_column(Integer,default=1,nullable=False)
    archived:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)


class Membership(Base):
    __tablename__='group_memberships'
    group_id:Mapped[str]=mapped_column(ForeignKey('travel_groups.id',ondelete='CASCADE'),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    role:Mapped[str]=mapped_column(String(10),default='member',nullable=False)
    joined_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(CheckConstraint("role IN ('owner','member')"),)


class MemberPreference(Base):
    __tablename__='member_preferences'
    group_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[str]=mapped_column(String(36),primary_key=True)
    values:Mapped[dict]=mapped_column(JSON,nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now,nullable=False)
    __table_args__=(ForeignKeyConstraint(['group_id','user_id'],['group_memberships.group_id','group_memberships.user_id'],ondelete='CASCADE'),)


class GroupRecommendation(Base):
    __tablename__='group_recommendations'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    group_id:Mapped[str]=mapped_column(ForeignKey('travel_groups.id',ondelete='CASCADE'),nullable=False,index=True)
    created_by:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
    group_revision:Mapped[int]=mapped_column(Integer,nullable=False)
    method:Mapped[str]=mapped_column(String(30),nullable=False)
    filters:Mapped[dict]=mapped_column(JSON,nullable=False)
    warnings:Mapped[list]=mapped_column(JSON,nullable=False)
    payload:Mapped[dict]=mapped_column(JSON,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,nullable=False)
    __table_args__=(UniqueConstraint('id','group_id'),)


class Vote(Base):
    __tablename__='votes'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    group_id:Mapped[str]=mapped_column(String(36),nullable=False)
    recommendation_id:Mapped[str]=mapped_column(String(36),nullable=False)
    user_id:Mapped[str]=mapped_column(String(36),nullable=False)
    destination_id:Mapped[str]=mapped_column(String(160),nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now,nullable=False)
    __table_args__=(UniqueConstraint('recommendation_id','user_id'),
        ForeignKeyConstraint(['recommendation_id','group_id'],['group_recommendations.id','group_recommendations.group_id'],ondelete='CASCADE'),
        ForeignKeyConstraint(['group_id','user_id'],['group_memberships.group_id','group_memberships.user_id'],ondelete='CASCADE'))


class ItineraryItem(Base):
    __tablename__='itinerary_items'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    group_id:Mapped[str]=mapped_column(String(36),nullable=False,index=True)
    recommendation_id:Mapped[str]=mapped_column(String(36),nullable=False)
    destination_id:Mapped[str]=mapped_column(String(160),nullable=False)
    destination_snapshot:Mapped[dict]=mapped_column(JSON,nullable=False)
    position:Mapped[int]=mapped_column(Integer,nullable=False)
    planned_date:Mapped[date | None]=mapped_column(Date,nullable=True)
    notes:Mapped[str]=mapped_column(String(1000),default='',nullable=False)
    created_by:Mapped[str]=mapped_column(ForeignKey('users.id'),nullable=False)
    __table_args__=(UniqueConstraint('group_id','position'),CheckConstraint('position > 0'),
        ForeignKeyConstraint(['recommendation_id','group_id'],['group_recommendations.id','group_recommendations.group_id'],ondelete='CASCADE'))
