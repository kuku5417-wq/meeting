"""기준정보(마스터) 모델 — docs/03 §3 「기준정보」 + department·person.

ID 는 CSV 의 사람이 읽는 값(`SN2511`, `EQ-SN2511-GE-02`, `D3`)을 그대로 PK 로 쓴다.
`alias` 만 CSV 에 id 가 없어 정수 자동번호다.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Department(Base):
    __tablename__ = "department"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class Person(Base):
    __tablename__ = "person"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))   # 화면 표시는 마스킹 대상(공통 규칙 7)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))


class ShipType(Base):
    __tablename__ = "ship_type"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))


class SisterGroup(Base):
    __tablename__ = "sister_group"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class Hull(Base):
    __tablename__ = "hull"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    ship_type_id: Mapped[str | None] = mapped_column(ForeignKey("ship_type.id"))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("owner.id"))
    sister_group_id: Mapped[str | None] = mapped_column(ForeignKey("sister_group.id"))
    stage: Mapped[str | None] = mapped_column(String(32))
    delivery_date: Mapped[date | None] = mapped_column(Date)
    # pjtlist 동기화(2026-10-21) — 프로젝트명·도크·선급·출처(pjtlist / csv)
    title: Mapped[str | None] = mapped_column(String(128))
    dock: Mapped[str | None] = mapped_column(String(32))
    ship_class: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(16))


class System(Base):
    __tablename__ = "system"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("system.id"))


class Maker(Base):
    __tablename__ = "maker"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))


class EquipmentModel(Base):
    __tablename__ = "equipment_model"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    maker_id: Mapped[str | None] = mapped_column(ForeignKey("maker.id"))
    name: Mapped[str] = mapped_column(String(128))
    model_no: Mapped[str | None] = mapped_column(String(64))


class InstalledEquipment(Base):
    __tablename__ = "installed_equipment"
    id: Mapped[str] = mapped_column(String(48), primary_key=True)   # EQ-{호선}-{시스템약어}-{2자리}
    hull_id: Mapped[str] = mapped_column(ForeignKey("hull.id"))
    equipment_model_id: Mapped[str | None] = mapped_column(ForeignKey("equipment_model.id"))
    system_id: Mapped[str | None] = mapped_column(ForeignKey("system.id"))
    name: Mapped[str] = mapped_column(String(128))
    unit_no: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[str | None] = mapped_column(String(128))


class Component(Base):
    __tablename__ = "component"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    equipment_model_id: Mapped[str | None] = mapped_column(ForeignKey("equipment_model.id"))
    name: Mapped[str] = mapped_column(String(128))


class TestItem(Base):
    __tablename__ = "test_item"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    system_id: Mapped[str | None] = mapped_column(ForeignKey("system.id"))


class SymptomCode(Base):
    __tablename__ = "symptom_code"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("symptom_code.id"))


class CauseCode(Base):
    __tablename__ = "cause_code"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("cause_code.id"))


class Alias(Base):
    """별칭 사전 — 현장 표기 → 기준정보 ID. target_kind 별로 가리키는 테이블이 달라 FK 를 걸지 않는다."""
    __tablename__ = "alias"
    __table_args__ = (UniqueConstraint("text", "target_kind", "scope_hull_id", name="uq_alias_text_scope"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String(128), index=True)
    target_kind: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(48))
    scope_hull_id: Mapped[str | None] = mapped_column(ForeignKey("hull.id"))
    source: Mapped[str] = mapped_column(String(16), default="seed")   # seed / user
    created_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
