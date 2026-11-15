"""Generates the colour-coded logical schema (ER diagram) from the ORM models.

    python -m scripts.generate_er        # needs Graphviz ("dot") installed
Output: docs/er-diagram.svg, docs/er-diagram.png, docs/er-diagram.dot
"""

import subprocess
from pathlib import Path

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

import app.db.models as models
from app.db.base import Base

DOCS = Path(__file__).resolve().parents[2] / "docs"
COLOURS = {  # one colour per block of the schema
    "Reference data": "#E7E6E6", "Identity": "#F8CBAD", "Course materials": "#BDD7EE",
    "Assessment": "#FFE699", "Learner model": "#C6E0B4", "Chat": "#D9C3E9", "Experiment": "#F4B6C2",
}


def column_label(table, col) -> str:
    marks = []
    if col.primary_key:
        marks.append("PK")
    if col.foreign_keys:
        marks.append("FK")
    unique_cols = {tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}
    if col.unique or (col.name,) in unique_cols:
        marks.append("UQ")
    null = "" if col.nullable else " NOT NULL"
    type_name = str(col.type).split("(")[0].lower() if "VECTOR" not in str(col.type) else "vector(384)"
    if hasattr(col.type, "enums") and col.type.name:
        type_name = col.type.name
    return f'<TR><TD ALIGN="LEFT">{" ".join(marks)}</TD><TD ALIGN="LEFT">{col.name}</TD><TD ALIGN="LEFT"><FONT COLOR="#555555">{type_name}{null}</FONT></TD></TR>'


def build_dot() -> str:
    lines = ['digraph ER {', 'graph [rankdir=LR, fontname="Helvetica", fontsize=20, nodesep=0.35, ranksep=1.1, '
             'label="AdaptED — logical schema (PostgreSQL 16 + pgvector)", labelloc=t, pad=0.3];',
             'node [shape=plaintext, fontname="Helvetica", fontsize=10];', 'edge [color="#666666", arrowsize=0.6];']
    for group, tables in models.TABLE_GROUPS.items():
        colour = COLOURS[group]
        lines.append(f'subgraph "cluster_{group}" {{ label="{group}"; style="rounded,filled"; fillcolor="{colour}40"; color="{colour}"; fontsize=14;')
        for name in tables:
            t = Base.metadata.tables[name]
            rows = "".join(column_label(t, c) for c in t.columns)
            lines.append(f'"{name}" [label=<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="3" BGCOLOR="white">'
                         f'<TR><TD COLSPAN="3" BGCOLOR="{colour}"><B>{name}</B></TD></TR>{rows}</TABLE>>];')
        lines.append("}")
    for t in Base.metadata.tables.values():
        for fk in (c for c in t.constraints if isinstance(c, ForeignKeyConstraint)):
            target = fk.referred_table.name
            one_to_one = len(fk.columns) == 1 and next(iter(fk.columns)).unique
            label = "1:1" if one_to_one else "N:1"
            lines.append(f'"{t.name}" -> "{target}" [label="{label}", fontsize=8];')
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    dot = DOCS / "er-diagram.dot"
    dot.write_text(build_dot(), encoding="utf-8")
    for fmt in ("svg", "png"):
        subprocess.run(["dot", f"-T{fmt}", "-Gdpi=110", str(dot), "-o", str(DOCS / f"er-diagram.{fmt}")], check=True)
    print("written:", ", ".join(str(DOCS / f"er-diagram.{f}") for f in ("dot", "svg", "png")))


if __name__ == "__main__":
    main()
