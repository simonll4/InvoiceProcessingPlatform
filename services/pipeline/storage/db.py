"""Persistence helpers for invoice_v1 records."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Optional

from loguru import logger
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from services.pipeline.config.settings import DB_URL

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    path = Column(String, nullable=False)
    file_hash = Column(String, nullable=True, unique=True, index=True)
    raw_text = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)

    invoice_number = Column(String, nullable=True)
    invoice_date = Column(String, nullable=False)
    vendor_name = Column(String, nullable=False)
    vendor_tax_id = Column(String, nullable=True)
    buyer_name = Column(String, nullable=True)
    currency_code = Column(String, nullable=False)
    subtotal_cents = Column(Integer, nullable=True)
    tax_cents = Column(Integer, nullable=True)
    total_cents = Column(Integer, nullable=False)
    due_date = Column(String, nullable=True)

    confidence = Column(Float, nullable=True)
    warnings = Column(Text, nullable=True)

    items = relationship("InvoiceItem", cascade="all, delete-orphan", back_populates="document")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    idx = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    qty = Column(Float, nullable=False)
    unit_price_cents = Column(Integer, nullable=True)
    line_total_cents = Column(Integer, nullable=False)
    category = Column(String, nullable=True)

    document = relationship("Document", back_populates="items")


engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


init_db()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def get_document_by_hash(file_hash: Optional[str]) -> Optional[dict]:
    if not file_hash:
        return None
    with session_scope() as session:
        result = session.execute(select(Document).where(Document.file_hash == file_hash)).scalar_one_or_none()
        if not result:
            return None
        return json.loads(result.raw_json)


def save_document(path: str, file_hash: Optional[str], raw_text: str, payload: dict) -> int:
    warnings = None
    confidence = None
    notes = payload.get("notes")
    if isinstance(notes, dict):
        warnings = json.dumps(notes.get("warnings")) if notes.get("warnings") else None
        confidence = notes.get("confidence")

    invoice = payload["invoice"]

    with session_scope() as session:
        doc = Document(
            path=path,
            file_hash=file_hash,
            raw_text=raw_text,
            raw_json=json.dumps(payload, ensure_ascii=False),
            invoice_number=invoice.get("invoice_number"),
            invoice_date=invoice["invoice_date"],
            vendor_name=invoice["vendor_name"],
            vendor_tax_id=invoice.get("vendor_tax_id"),
            buyer_name=invoice.get("buyer_name"),
            currency_code=invoice["currency_code"],
            subtotal_cents=invoice.get("subtotal_cents"),
            tax_cents=invoice.get("tax_cents"),
            total_cents=invoice["total_cents"],
            due_date=invoice.get("due_date"),
            confidence=confidence,
            warnings=warnings,
        )
        session.add(doc)
        session.flush()

        for item in payload.get("items", []):
            session.add(
                InvoiceItem(
                    document_id=doc.id,
                    idx=item["idx"],
                    description=item["description"],
                    qty=item.get("qty", 1.0),
                    unit_price_cents=item.get("unit_price_cents"),
                    line_total_cents=item["line_total_cents"],
                    category=item.get("category"),
                )
            )

        logger.info("Persisted document %s", doc.id)
        return doc.id


