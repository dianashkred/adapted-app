from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

import app.db.models as models
from app.db.base import Base
from scripts.data_dictionary_text import COLUMNS, TABLES

OUT = Path(__file__).resolve().parents[2] / "docs" / "data-dictionary.md"


def type_name(col) -> str:
    if hasattr(col.type, "enums") and getattr(col.type, "name", None):
        return f"enum `{col.type.name}` ({', '.join(col.type.enums)})"
    return str(col.type).lower().replace("varchar", "varchar").replace("datetime", "timestamptz")


def main() -> None:
    out = ["# Data dictionary", "",
           "Generated from the ORM models by `python -m scripts.generate_data_dictionary`. "
           "Layers: one transactional (OLTP) layer in schema `public`; pseudonymised read-only views in schema `analytics`.", ""]
    for group, tables in models.TABLE_GROUPS.items():
        out += [f"## {group}", ""]
        for name in tables:
            t = Base.metadata.tables[name]
            out += [f"### `{name}`", "", TABLES[name][1], "",
                    "| Column | Type | Null | Key | Description |", "| --- | --- | --- | --- | --- |"]
            for c in t.columns:
                keys = []
                if c.primary_key: keys.append("PK")
                for fk in c.foreign_keys:
                    keys.append(f"FK → {fk.column.table.name}.{fk.column.name} ({fk.ondelete or 'NO ACTION'})")
                if c.unique: keys.append("UQ")
                default = f" default `{c.server_default.arg}`" if c.server_default is not None and hasattr(c.server_default, "arg") else ""
                out.append(f"| `{c.name}` | {type_name(c)}{default} | {'yes' if c.nullable else 'no'} | {', '.join(keys)} | {COLUMNS[name].get(c.name, '')} |")
            checks = [c for c in t.constraints if isinstance(c, CheckConstraint)]
            uniques = [c for c in t.constraints if isinstance(c, UniqueConstraint) and len(c.columns) > 1]
            if checks or uniques:
                out += ["", "**Data-quality rules (enforced by the database):**", ""]
                for u in uniques:
                    out.append(f"- UNIQUE ({', '.join(u.columns.keys())})")
                for ck in checks:
                    out.append(f"- CHECK `{ck.name if isinstance(ck.name, str) else ''}`: `{ck.sqltext}`")
            idx = [i for i in t.indexes]
            if idx:
                out += ["", "**Indexes:** " + ", ".join(f"`{i.name}`" for i in idx)]
            out.append("")
    OUT.write_text("\n".join(out), encoding="utf-8")
    print("written:", OUT)


if __name__ == "__main__":
    main()
