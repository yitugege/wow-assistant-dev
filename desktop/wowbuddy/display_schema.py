"""098ea0 的空字段显示结构：仅含契约元数据，不冒充采样读数。"""
from dataclasses import dataclass, field
from typing import Mapping

from .pipeline import DecisionPipeline, Frame


@dataclass(frozen=True)
class BlankDisplayValue:
    value_text: str = ""
    detail: str = ""
    raw_rgb: None = None
    raw_value: None = None


@dataclass(frozen=True)
class LayoutRow:
    index: int
    key: str
    label: str
    type: str
    applicable: bool
    decoded: BlankDisplayValue = field(default_factory=BlankDisplayValue)
    physical_row: int | None = None
    is_common: bool = False
    note: str = ""


@dataclass(frozen=True)
class LayoutFrame:
    spec_id: str
    protocol: str
    rows: tuple[LayoutRow, ...]
    status: str = "layout_only"
    values: Mapping[str, str] = field(default_factory=dict)
    raw_colors: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return False


def blank_schema(pipeline: DecisionPipeline, source: Frame, spec_id: str) -> LayoutFrame:
    if source.protocol == "old":
        class_only = pipeline.old.contract.get("classOnlyFields", {})
        spec_number = int(spec_id) if spec_id else 0
        rows = tuple(LayoutRow(index, definition["id"], definition.get("label", ""),
                               definition["type"], definition["id"] not in class_only
                               or spec_number in class_only[definition["id"]],
                               is_common=index < len(pipeline.old.contract.get("commonFields", [])),
                               note=definition.get("note", ""))
                     for index, definition in enumerate(pipeline.old.field_definitions(spec_id)))
    elif source.protocol == "readable":
        rows = tuple(LayoutRow(index, key, key, kind, True, physical_row=row)
                     for index, (key, kind, row) in enumerate(pipeline.readable.field_definitions(spec_id)))
    else:
        raise NotImplementedError(f"unsupported display schema protocol: {source.protocol}")
    return LayoutFrame(spec_id, source.protocol, rows)
