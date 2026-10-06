"""A durable receipt preventing repeated updates from the identical evidence set."""
from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from agentic_core.database.base import Base


class EvidenceUse(Base):
    __tablename__='aries_learning_evidence_uses'
    __table_args__=(UniqueConstraint('kind','target','scope','digest',name='uq_learning_evidence_use'),)
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    kind: Mapped[str]=mapped_column(String(40))
    target: Mapped[str]=mapped_column(String(200))
    scope: Mapped[str]=mapped_column(String(120),default='')
    digest: Mapped[str]=mapped_column(String(64))
