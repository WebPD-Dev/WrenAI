"""Unit tests for dbt project and artifact loading helpers."""

from __future__ import annotations

import json

import pytest
import yaml

from wren.dbt import (
    DbtLoadError,
    convert_dbt_project_to_wren_project,
    convert_dbt_target_to_wren_profile,
    default_wren_profile_name,
    load_compiled_sql,
    load_dbt_artifacts,
    load_dbt_profiles,
    map_dbt_adapter_to_wren,
    resolve_dbt_target,
    resolve_env_vars,
)


def _write_basic_dbt_project(tmp_path):
    project_dir = tmp_path / "jaffle_shop"
    target_dir = project_dir / "build"
    compiled_dir = target_dir / "compiled" / "jaffle_shop" / "models"
    compiled_dir.mkdir(parents=True)

    (project_dir / "dbt_project.yml").write_text(
        "name: jaffle_shop\nprofile: jaffle_shop\ntarget-path: build\n"
    )
    (target_dir / "manifest.json").write_text(
        json.dumps(
            {
                "metadata": {"adapter_type": "duckdb"},
                "nodes": {
                    "model.jaffle_shop.orders": {
                        "resource_type": "model",
                        "name": "orders",
                    }
                },
            }
        )
    )
    (target_dir / "catalog.json").write_text(
        json.dumps(
            {
                "nodes": {
                    "model.jaffle_shop.orders": {
                        "metadata": {"type": "TABLE"},
                        "columns": {"id": {"type": "integer"}},
                    }
                }
            }
        )
    )
    (target_dir / "run_results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "unique_id": "test.jaffle_shop.not_null_orders_id",
                        "status": "pass",
                    }
                ]
            }
        )
    )
    (compiled_dir / "orders.sql").write_text("select * from orders\n")

    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text(
        "jaffle_shop:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        "      path: \"{{ env_var('JAFFLE_DUCKDB_PATH') }}\"\n"
    )
    return project_dir, profiles_path


@pytest.mark.unit
class TestAdapterMapping:
    def test_map_known_adapter(self):
        assert map_dbt_adapter_to_wren("duckdb") == "duckdb"
        assert map_dbt_adapter_to_wren("sqlserver") == "mssql"

    def test_map_unknown_adapter(self):
        with pytest.raises(DbtLoadError, match="Unsupported dbt adapter"):
            map_dbt_adapter_to_wren("fabric")


@pytest.mark.unit
class TestEnvResolution:
    def test_resolve_env_var_string(self):
        value = "{{ env_var('DBT_PASSWORD') }}"
        resolved = resolve_env_vars(value, env={"DBT_PASSWORD": "secret"})
        assert resolved == "secret"

    def test_resolve_env_var_with_default(self):
        value = "{{ env_var('DBT_SCHEMA', 'analytics') }}"
        resolved = resolve_env_vars(value, env={})
        assert resolved == "analytics"

    def test_resolve_env_var_nested(self):
        payload = {
            "password": "{{ env_var('DBT_PASSWORD') }}",
            "schema": "{{ env_var('DBT_SCHEMA', 'public') }}",
            "extras": ["{{ env_var('DBT_ROLE', 'analyst') }}"],
        }
        resolved = resolve_env_vars(payload, env={"DBT_PASSWORD": "secret"})
        assert resolved["password"] == "secret"
        assert resolved["schema"] == "public"
        assert resolved["extras"] == ["analyst"]

    def test_resolve_env_var_missing_without_default(self):
        with pytest.raises(DbtLoadError, match="DBT_PASSWORD"):
            resolve_env_vars("{{ env_var('DBT_PASSWORD') }}", env={})


@pytest.mark.unit
class TestResolveDbtTarget:
    def test_load_profiles_accepts_directory_path(self, tmp_path):
        profiles_dir = tmp_path / "dbt"
        profiles_dir.mkdir()
        (profiles_dir / "profiles.yml").write_text("jaffle_shop: {}\n")

        assert load_dbt_profiles(profiles_dir) == {"jaffle_shop": {}}

    def test_load_profiles_uses_dbt_profiles_dir(self, tmp_path, monkeypatch):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiles.yml").write_text("jaffle_shop: {}\n")
        monkeypatch.setenv("DBT_PROFILES_DIR", str(profiles_dir))

        assert load_dbt_profiles() == {"jaffle_shop": {}}

    def test_load_profiles_uses_cwd_before_home_fallback(self, tmp_path, monkeypatch):
        (tmp_path / "profiles.yml").write_text("jaffle_shop: {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)

        assert load_dbt_profiles() == {"jaffle_shop": {}}

    def test_resolve_target_from_project_and_profiles(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        target = resolve_dbt_target(
            project_dir,
            profiles_path=profiles_path,
            env={"JAFFLE_DUCKDB_PATH": "/tmp/jaffle.duckdb"},
        )

        assert target.profile_name == "jaffle_shop"
        assert target.target_name == "dev"
        assert target.datasource == "duckdb"
        assert target.adapter_type == "duckdb"
        assert target.output["path"] == "/tmp/jaffle.duckdb"
        assert target.target_path == project_dir / "build"

    def test_resolve_target_missing_profile(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        (project_dir / "dbt_project.yml").write_text("name: jaffle_shop\n")

        with pytest.raises(DbtLoadError, match="missing 'profile'"):
            resolve_dbt_target(project_dir, profiles_path=profiles_path)

    def test_resolve_target_missing_output(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n  target: prod\n  outputs:\n    dev:\n      type: duckdb\n"
        )

        with pytest.raises(DbtLoadError, match="Available targets: dev"):
            resolve_dbt_target(project_dir, profiles_path=profiles_path)


@pytest.mark.unit
class TestConvertDbtTargetToWrenProfile:
    def test_default_profile_name(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        target = resolve_dbt_target(
            project_dir,
            profiles_path=profiles_path,
            env={"JAFFLE_DUCKDB_PATH": "/tmp/jaffle.duckdb"},
        )

        assert default_wren_profile_name(target) == "jaffle-shop-dev"

    def test_convert_duckdb_profile(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        target = resolve_dbt_target(
            project_dir,
            profiles_path=profiles_path,
            env={"JAFFLE_DUCKDB_PATH": "warehouse/jaffle.duckdb"},
        )

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile == {
            "datasource": "duckdb",
            "url": str((project_dir / "warehouse").resolve()),
            "format": "duckdb",
        }

    def test_convert_postgres_profile(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: postgres\n"
            "      host: localhost\n"
            "      port: 5432\n"
            "      dbname: analytics\n"
            "      user: postgres\n"
            "      password: secret\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile == {
            "datasource": "postgres",
            "host": "localhost",
            "port": "5432",
            "database": "analytics",
            "user": "postgres",
            "password": "secret",
        }

    def test_convert_postgres_profile_omits_missing_password(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: postgres\n"
            "      host: localhost\n"
            "      port: 5432\n"
            "      dbname: analytics\n"
            "      user: postgres\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile == {
            "datasource": "postgres",
            "host": "localhost",
            "port": "5432",
            "database": "analytics",
            "user": "postgres",
        }

    def test_convert_bigquery_profile_from_keyfile_json(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: bigquery\n"
            "      project: demo-project\n"
            "      dataset: analytics\n"
            "      keyfile_json:\n"
            "        client_email: analytics@example.com\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile["datasource"] == "bigquery"
        assert profile["bigquery_type"] == "dataset"
        assert profile["project_id"] == "demo-project"
        assert profile["dataset_id"] == "analytics"
        assert profile["credentials"]

    def test_map_starrocks_adapter(self):
        assert map_dbt_adapter_to_wren("starrocks") == "starrocks"

    def test_convert_starrocks_profile(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: starrocks\n"
            "      host: sr.example.com\n"
            "      port: 9030\n"
            "      schema: analytics\n"
            "      username: etl\n"
            "      password: secret\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile["datasource"] == "starrocks"
        assert profile["host"] == "sr.example.com"
        assert profile["port"] == "9030"
        assert profile["database"] == "analytics"
        assert profile["user"] == "etl"
        assert profile["password"] == "secret"

    def test_convert_starrocks_profile_rejects_custom_catalog(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: starrocks\n"
            "      host: sr.example.com\n"
            "      schema: analytics\n"
            "      username: etl\n"
            "      catalog: hive_catalog\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        with pytest.raises(DbtLoadError, match="catalog"):
            convert_dbt_target_to_wren_profile(target)

    def test_convert_databricks_profile_preserves_catalog(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: databricks\n"
            "      host: dbc.example.cloud.databricks.com\n"
            "      http_path: /sql/1.0/warehouses/abc\n"
            "      token: dapi-token\n"
            "      catalog: main\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        profile = convert_dbt_target_to_wren_profile(target)

        assert profile == {
            "datasource": "databricks",
            "databricks_type": "token",
            "server_hostname": "dbc.example.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc",
            "access_token": "dapi-token",
            "catalog": "main",
        }

    def test_convert_profile_missing_required_field(self, tmp_path):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        profiles_path.write_text(
            "jaffle_shop:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: postgres\n"
            "      host: localhost\n"
            "      port: 5432\n"
        )
        target = resolve_dbt_target(project_dir, profiles_path=profiles_path)

        with pytest.raises(DbtLoadError, match="dbname, database"):
            convert_dbt_target_to_wren_profile(target)


@pytest.mark.unit
class TestLoadDbtArtifacts:
    def test_import_normalizes_column_types_with_dbt_adapter(
        self, tmp_path, monkeypatch
    ):
        project_dir, profiles_path = _write_basic_dbt_project(tmp_path)
        monkeypatch.setenv("JAFFLE_DUCKDB_PATH", "warehouse/jaffle.duckdb")
        catalog_path = project_dir / "build" / "catalog.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["nodes"]["model.jaffle_shop.orders"]["columns"]["id"]["type"] = (
            "character varying(255)"
        )
        catalog_path.write_text(json.dumps(catalog))

        imported = convert_dbt_project_to_wren_project(
            project_dir, profiles_path=profiles_path
        )

        model_file = next(
            file
            for file in imported.files
            if file.relative_path == "models/orders/metadata.yml"
        )
        metadata = yaml.safe_load(model_file.content)
        assert metadata["columns"][0]["type"] == "VARCHAR(255)"

    def test_load_artifacts(self, tmp_path):
        project_dir, _profiles_path = _write_basic_dbt_project(tmp_path)

        artifacts = load_dbt_artifacts(project_dir)

        assert artifacts.project_dir == project_dir.resolve()
        assert artifacts.target_path == (project_dir / "build").resolve()
        assert "model.jaffle_shop.orders" in artifacts.manifest["nodes"]
        assert "model.jaffle_shop.orders" in artifacts.catalog["nodes"]
        assert artifacts.run_results["results"][0]["status"] == "pass"
        assert (
            artifacts.compiled_sql["jaffle_shop/models/orders.sql"]
            == "select * from orders\n"
        )

    def test_load_artifacts_without_run_results(self, tmp_path):
        project_dir, _profiles_path = _write_basic_dbt_project(tmp_path)
        (project_dir / "build" / "run_results.json").unlink()

        artifacts = load_dbt_artifacts(project_dir)

        assert artifacts.run_results is None

    def test_load_artifacts_missing_manifest(self, tmp_path):
        project_dir, _profiles_path = _write_basic_dbt_project(tmp_path)
        (project_dir / "build" / "manifest.json").unlink()

        with pytest.raises(DbtLoadError, match="dbt manifest file not found"):
            load_dbt_artifacts(project_dir)

    def test_load_artifacts_invalid_catalog_json(self, tmp_path):
        project_dir, _profiles_path = _write_basic_dbt_project(tmp_path)
        (project_dir / "build" / "catalog.json").write_text("{")

        with pytest.raises(DbtLoadError, match="dbt catalog is not valid JSON"):
            load_dbt_artifacts(project_dir)

    def test_load_compiled_sql_missing_dir(self, tmp_path):
        assert load_compiled_sql(tmp_path / "missing") == {}

    def test_load_artifacts_missing_catalog_has_actionable_hint(self, tmp_path):
        project_dir, _profiles_path = _write_basic_dbt_project(tmp_path)
        (project_dir / "build" / "catalog.json").unlink()

        with pytest.raises(DbtLoadError, match="dbt docs generate"):
            load_dbt_artifacts(project_dir)


def _write_shop_dbt_project(tmp_path, *, order_lines_node=None, extra_nodes=None):
    """A dbt project whose ``order_lines`` declares foreign keys to ``parts``.

    Node shapes follow the manifest dbt-core 1.12 writes after ``dbt build`` and
    ``dbt docs generate``: a constraint's ``to`` holds the referenced node's
    ``relation_name``.
    """
    project_dir = tmp_path / "shop"
    target_dir = project_dir / "target"
    target_dir.mkdir(parents=True)
    (project_dir / "dbt_project.yml").write_text("name: shop\nprofile: shop\n")
    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text(
        "shop:\n  target: dev\n  outputs:\n    dev:\n"
        "      type: duckdb\n      path: shop.duckdb\n"
    )

    def model(name, constraints=(), columns=None):
        return {
            "resource_type": "model",
            "name": name,
            "database": "shop",
            "schema": "main",
            "alias": name,
            "relation_name": f'"shop"."main"."{name}"',
            "config": {"materialized": "table"},
            "constraints": list(constraints),
            "columns": columns or {},
        }

    nodes = {
        "model.shop.parts": model("parts"),
        "model.shop.customers": model("customers"),
        "model.shop.order_lines": order_lines_node
        or model(
            "order_lines",
            constraints=[
                {
                    "type": "foreign_key",
                    "name": "order_lines_parts_fk",
                    "expression": None,
                    "to": '"shop"."main"."parts"',
                    "to_columns": ["part_id", "supplier_id"],
                    "columns": ["part_id", "supplier_id"],
                }
            ],
            columns={
                "customer_id": {
                    "name": "customer_id",
                    "constraints": [
                        {
                            "type": "foreign_key",
                            "name": None,
                            "expression": None,
                            "to": '"shop"."main"."customers"',
                            "to_columns": ["id"],
                        }
                    ],
                }
            },
        ),
        **(extra_nodes or {}),
    }
    catalog_columns = {
        "model.shop.parts": ["part_id", "supplier_id", "brand"],
        "model.shop.customers": ["id", "name"],
        "model.shop.order_lines": ["line_id", "part_id", "supplier_id", "customer_id"],
    }
    (target_dir / "manifest.json").write_text(
        json.dumps({"metadata": {"adapter_type": "duckdb"}, "nodes": nodes})
    )
    (target_dir / "catalog.json").write_text(
        json.dumps(
            {
                "nodes": {
                    unique_id: {
                        "columns": {
                            name: {"type": "INTEGER", "index": i}
                            for i, name in enumerate(names, start=1)
                        }
                    }
                    for unique_id, names in catalog_columns.items()
                }
            }
        )
    )
    return project_dir, profiles_path


def _imported_relationships(imported):
    rel_file = next(f for f in imported.files if f.relative_path == "relationships.yml")
    return yaml.safe_load(rel_file.content)["relationships"]


@pytest.mark.unit
class TestDbtForeignKeyConstraints:
    def test_model_and_column_level_foreign_keys_become_relationships(self, tmp_path):
        project_dir, profiles_path = _write_shop_dbt_project(tmp_path)

        imported = convert_dbt_project_to_wren_project(
            project_dir, profiles_path=profiles_path
        )

        assert _imported_relationships(imported) == [
            {
                "name": "order_lines_to_customers",
                "models": ["order_lines", "customers"],
                "join_type": "MANY_TO_ONE",
                "condition": "order_lines.customer_id = customers.id",
                "properties": {"source": "dbt_constraint"},
            },
            {
                "name": "order_lines_to_parts",
                "models": ["order_lines", "parts"],
                "join_type": "MANY_TO_ONE",
                "condition": "order_lines.part_id = parts.part_id "
                "AND order_lines.supplier_id = parts.supplier_id",
                "properties": {"source": "dbt_constraint"},
            },
        ]
        assert imported.relationship_count == 2
        assert imported.skipped_foreign_keys == []

    def test_relationships_test_and_constraint_on_same_key_yield_one_relationship(
        self, tmp_path
    ):
        test_node = {
            "resource_type": "test",
            "name": "relationships_order_lines_customer_id__id__ref_customers_",
            "attached_node": "model.shop.order_lines",
            "column_name": "customer_id",
            "test_metadata": {
                "name": "relationships",
                "kwargs": {
                    "column_name": "customer_id",
                    "to": "ref('customers')",
                    "field": "id",
                },
            },
            "depends_on": {"nodes": ["model.shop.customers", "model.shop.order_lines"]},
        }
        project_dir, profiles_path = _write_shop_dbt_project(
            tmp_path,
            extra_nodes={"test.shop.relationships_order_lines_customer_id": test_node},
        )

        imported = convert_dbt_project_to_wren_project(
            project_dir, profiles_path=profiles_path
        )

        customers = [
            rel
            for rel in _imported_relationships(imported)
            if rel["models"] == ["order_lines", "customers"]
        ]
        assert customers == [
            {
                "name": "order_lines_to_customers",
                "models": ["order_lines", "customers"],
                "join_type": "MANY_TO_ONE",
                "condition": "order_lines.customer_id = customers.id",
                "properties": {"source": "dbt_test"},
            }
        ]

    @pytest.mark.parametrize(
        ("constraint", "reason"),
        [
            (
                {"type": "foreign_key", "expression": "parts (part_id, supplier_id)"},
                "order_lines(part_id, supplier_id) -> parts (part_id, supplier_id): "
                "no `to`; the `expression`-only form (dbt < 1.9) is not imported",
            ),
            (
                {"type": "foreign_key", "to": "ref('parts')"},
                "order_lines(part_id, supplier_id) -> ref('parts'): `to` matches "
                "no imported model or source (run `dbt docs generate` so it holds "
                "the relation name)",
            ),
            (
                {
                    "type": "foreign_key",
                    "to": '"shop"."main"."parts"',
                    "to_columns": ["part_id"],
                },
                'order_lines(part_id, supplier_id) -> "shop"."main"."parts": '
                "`columns` and `to_columns` need the same, non-zero length",
            ),
            (
                {
                    "type": "foreign_key",
                    "to": '"shop"."main"."parts"',
                    "to_columns": ["part_id", "vendor_id"],
                },
                'order_lines(part_id, supplier_id) -> "shop"."main"."parts": '
                "no catalog column parts.vendor_id",
            ),
        ],
        ids=["expression-only", "unresolved-ref", "length-mismatch", "missing-column"],
    )
    def test_unusable_foreign_key_is_skipped_and_reported(
        self, tmp_path, constraint, reason
    ):
        order_lines = {
            "resource_type": "model",
            "name": "order_lines",
            "database": "shop",
            "schema": "main",
            "alias": "order_lines",
            "relation_name": '"shop"."main"."order_lines"',
            "config": {"materialized": "table"},
            "constraints": [{"columns": ["part_id", "supplier_id"], **constraint}],
            "columns": {},
        }
        project_dir, profiles_path = _write_shop_dbt_project(
            tmp_path, order_lines_node=order_lines
        )

        imported = convert_dbt_project_to_wren_project(
            project_dir, profiles_path=profiles_path
        )

        assert _imported_relationships(imported) == []
        assert imported.skipped_foreign_keys == [reason]
