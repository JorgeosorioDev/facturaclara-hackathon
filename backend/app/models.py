"""Modelos SQLAlchemy 2.x — montos BigInteger, nunca float."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proveedor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nit_normalizado: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fecha: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iva: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    categoria: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    imagen_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creada_en: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, nullable=False
    )

    items: Mapped[list["Item"]] = relationship(
        "Item", back_populates="factura", cascade="all, delete-orphan"
    )


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    factura_id: Mapped[int] = mapped_column(
        ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False
    )
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    cantidad: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    precio_unitario: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    factura: Mapped["Factura"] = relationship("Factura", back_populates="items")


class Categoria(Base):
    __tablename__ = "categorias"

    nombre: Mapped[str] = mapped_column(String(32), primary_key=True)


CATEGORIAS_FIJAS = [
    "papeleria",
    "transporte",
    "servicios",
    "alimentacion",
    "salud",
    "otros",
]
