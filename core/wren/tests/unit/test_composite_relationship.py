"""End-to-end tests for composite-key relationships (Canner/WrenAI#1738).

A relationship whose foreign key spans several columns is declared as one
relationship whose ``condition`` ANDs one equality per column pair, and the
referenced model declares a list-form ``primary_key``. These tests build a YAML
project with ``build_json`` and run real queries on DuckDB through
``WrenEngine``, so they cover the YAML loader, sub-manifest extraction, the
wren-core planner and the connector together.

The data shares ``part_id`` between parts from different suppliers, so a join
that kept only the first equality would duplicate or mis-sum rows.
"""

from __future__ import annotations

import base64
import textwrap
from pathlib import Path

import duckdb
import orjson
import pytest

from wren import WrenEngine
from wren.context import build_json, validate_project
from wren.model.data_source import DataSource
from wren.model.error import WrenError

pytestmark = pytest.mark.unit

_MANY_TO_ONE = (
    "order_lines.part_id = parts.part_id "
    "AND order_lines.supplier_id = parts.supplier_id"
)
_ONE_TO_MANY = (
    "parts.part_id = order_lines.part_id "
    "AND parts.supplier_id = order_lines.supplier_id"
)


@pytest.fixture(scope="module")
def db_dir(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("composite_fk_db")
    con = duckdb.connect(str(path / "shop.duckdb"))
    con.execute(
        "CREATE TABLE parts (part_id INT, supplier_id INT, brand VARCHAR, "
        "PRIMARY KEY (part_id, supplier_id))"
    )
    con.execute(
        "INSERT INTO parts VALUES (1, 10, 'Acme'), (1, 20, 'Bolt'), (2, 10, 'Cog')"
    )
    con.execute(
        "CREATE TABLE order_lines (line_id INT PRIMARY KEY, part_id INT, "
        "supplier_id INT, qty INT)"
    )
    con.execute(
        "INSERT INTO order_lines VALUES "
        "(100, 1, 10, 5), (101, 1, 20, 7), (102, 2, 10, 3), (103, 1, 20, 1)"
    )
    con.close()
    return path


def _write_project(root: Path, many_to_one_condition: str = _MANY_TO_ONE) -> Path:
    files = {
        "wren_project.yml": """
            schema_version: 5
            name: composite_fk
            catalog: wren
            schema: public
            data_source: duckdb
        """,
        "models/parts/metadata.yml": """
            name: parts
            table_reference:
              catalog: shop
              schema: main
              table: parts
            columns:
              - name: part_id
                type: INTEGER
              - name: supplier_id
                type: INTEGER
              - name: brand
                type: VARCHAR
              - name: order_lines
                type: order_lines
                relationship: parts_order_lines
              - name: total_qty
                type: BIGINT
                is_calculated: true
                expression: sum(order_lines.qty)
            primary_key:
              - part_id
              - supplier_id
        """,
        "models/order_lines/metadata.yml": """
            name: order_lines
            table_reference:
              catalog: shop
              schema: main
              table: order_lines
            columns:
              - name: line_id
                type: INTEGER
              - name: part_id
                type: INTEGER
              - name: supplier_id
                type: INTEGER
              - name: qty
                type: INTEGER
              - name: part
                type: parts
                relationship: order_lines_parts
              - name: part_brand
                type: VARCHAR
                is_calculated: true
                expression: part.brand
            primary_key: line_id
        """,
        "relationships.yml": f"""
            relationships:
              - name: order_lines_parts
                models: [order_lines, parts]
                join_type: MANY_TO_ONE
                condition: {many_to_one_condition}
              - name: parts_order_lines
                models: [parts, order_lines]
                join_type: ONE_TO_MANY
                condition: {_ONE_TO_MANY}
        """,
    }
    for rel_path, body in files.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


def _engine(project: Path, db_dir: Path) -> WrenEngine:
    manifest = base64.b64encode(orjson.dumps(build_json(project))).decode()
    return WrenEngine(
        manifest,
        DataSource.duckdb,
        {"url": str(db_dir), "format": "duckdb"},
        fallback=False,
    )


def test_composite_key_project_validates(tmp_path):
    project = _write_project(tmp_path)

    errors = [e for e in validate_project(project) if e.level == "error"]

    assert errors == []


def test_many_to_one_joins_on_every_key_column(tmp_path, db_dir):
    project = _write_project(tmp_path)

    with _engine(project, db_dir) as engine:
        rows = engine.query(
            "SELECT line_id, part_brand FROM order_lines ORDER BY line_id"
        ).to_pylist()

    # Joining on part_id alone would return line 100 twice (Acme and Bolt).
    assert rows == [
        {"line_id": 100, "part_brand": "Acme"},
        {"line_id": 101, "part_brand": "Bolt"},
        {"line_id": 102, "part_brand": "Cog"},
        {"line_id": 103, "part_brand": "Bolt"},
    ]


def test_one_to_many_aggregates_per_composite_primary_key(tmp_path, db_dir):
    project = _write_project(tmp_path)

    with _engine(project, db_dir) as engine:
        rows = engine.query(
            "SELECT part_id, supplier_id, total_qty FROM parts "
            "ORDER BY part_id, supplier_id"
        ).to_pylist()

    # Joining on part_id alone would give part (1, 10) the 13 units of all
    # three part-1 lines instead of its own 5.
    assert rows == [
        {"part_id": 1, "supplier_id": 10, "total_qty": 5},
        {"part_id": 1, "supplier_id": 20, "total_qty": 8},
        {"part_id": 2, "supplier_id": 10, "total_qty": 3},
    ]


@pytest.mark.parametrize(
    "condition",
    [
        "order_lines.part_id = parts.part_id "
        "OR order_lines.supplier_id = parts.supplier_id",
        "order_lines.part_id = parts.part_id "
        "AND order_lines.supplier_id > parts.supplier_id",
    ],
    ids=["or", "non-equality"],
)
def test_condition_must_be_a_conjunction_of_equalities(tmp_path, db_dir, condition):
    project = _write_project(tmp_path, many_to_one_condition=condition)

    with _engine(project, db_dir) as engine:
        with pytest.raises(WrenError, match="conjunction of column equalities"):
            engine.query("SELECT part_brand FROM order_lines")
