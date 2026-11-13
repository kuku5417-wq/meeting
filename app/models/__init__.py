"""SQLAlchemy 모델 — docs/03_데이터모델.md 와 1:1. 스키마를 바꾸면 그 문서도 함께 고친다."""
from app.models.masters import (  # noqa: F401
    Alias, CauseCode, Component, Department, EquipmentModel, Hull, InstalledEquipment, Maker,
    Owner, Person, ShipType, SisterGroup, SymptomCode, System, TestItem,
)
from app.models.others import (  # noqa: F401
    Annotation, BlockLink, CaseCard, LlmCallLog, Marker, Meeting, AppSetting, Directive, ImportJob, ImportPiece, MeetingCandidate, MeetingVersion, ReportItem, ReportItemBlock,
    MeetingComment, MetricCell, MetricDef, MetricTable, MetricValue, Photo, PhotoLink,
)
from app.models.writing import (  # noqa: F401
    AiFieldLog, Block, BlockEvent, BlockHistory, BlockTable, BlockTag, Closure, Memo, Section, SectionBlock,
    SourceSpan, Week,
)
