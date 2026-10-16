# CLAUDE.md — working guide for the WebPD-Dev fork

Working notes for Claude Code on this fork. They complement the upstream guides,
which Claude Code also loads:

- `.claude/CLAUDE.md` — upstream repo-wide guide: architecture, per-module commands,
  conventions and the **Contribution Bar**. Read the Contribution Bar before any PR.
- `core/<module>/.claude/CLAUDE.md` — per-module guides (wren-core, wren-core-base,
  wren-core-py, wren-core-wasm, wren). `sdk/*` has none.

Everything below was checked against the code on 2026-10-16 (HEAD `caa23ac`,
`wrenai` 0.16.0). When an upstream guide and the code disagree, the code wins: check
"Known stale statements" at the end before relying on a detail from the upstream guides.

## Fork, language, git

- `origin` is `github.com/WebPD-Dev/WrenAI`, a fork of `Canner/WrenAI`. `main` mirrors
  upstream; this file is the only fork-specific change. Keep it, and any other
  fork-only change, out of PRs aimed at upstream.
- Links to `Canner/WrenAI` in README, CONTRIBUTING and `skills/` point at upstream on
  purpose. Don't rewrite them to the fork.
- The cloud checkout is shallow (50 commits). For older history run
  `git fetch --deepen=<n>` or `git fetch --unshallow`.
- The maintainer writes in Italian and wants the final result of every task in
  Italian: replies, summaries, guides and reports, including the comments in example
  code written for them. Keep English terms only where Italian has no common
  equivalent, and explain them. Code, code comments, commit messages, PR text and
  repo docs stay in English, like the rest of the repo.
- Commits and PR titles use conventional commits. The PR-title validator
  (`.github/workflows/pull-request-title-validator.yaml`) accepts
  `feat fix perf deps revert docs chore refactor test build ci`. Scopes are free-form;
  the common ones are `wren`, `core`, `context`, `memory`, `mdl`, `wasm`, `sdk`, `deps`.
  `main`, `release` and `bindings` belong to the release bots.
  release-please builds changelogs and version bumps from these titles, so pick the type
  honestly: `fix:` needs a reproduced failure (see the Contribution Bar).
- The PR body follows `.github/pull_request_template.md`: Summary / What failure does this
  repair? (paste the real repro and error for `fix:`) / How is it tested? (does that test
  run in CI?) / Duplicate check.
- Never commit build or local output: `.venv/`, `target/`, `dist/`, `pkg/`,
  `node_modules/`, `.env*`, the workspace `Cargo.lock` (gitignored on purpose), or
  scratch test scripts.

## Repository map

| Path | What it is | Published as |
|---|---|---|
| `core/wren-core/` | Cargo workspace: `core/` (engine), `sqllogictest/`, `benchmarks/`, `wren-example/` | crates.io `wren-semantic-core` (lib `wren_core`) |
| `core/wren-core-base/` | Standalone crate: MDL manifest types and `ManifestBuilder`. `manifest-macro/` generates the `DataSource` enum and the PyO3 classes | crates.io `wren-core-base`, `wren-manifest-macro` |
| `core/wren-core-py/` | PyO3/maturin bindings. Python module `wren_core` | PyPI `wren-core-py` |
| `core/wren-core-wasm/` | Standalone crate plus TypeScript SDK (`sdk/src/index.ts`) for queries in the browser | npm `@wrenai/wren-core-wasm` |
| `core/wren/` | Python SDK and the `wren` CLI (Typer). Most day-to-day changes land here | PyPI `wrenai` |
| `core/wren-mdl/mdl.schema.json` | MDL JSON Schema. Maintained by hand; nothing validates against it | — |
| `sdk/wren-langchain/`, `sdk/wren-pydantic/` | Agent-framework toolkits over a Wren project | PyPI `wren-langchain`, `wren-pydantic` |
| `skills/` | Only a discovery stub (`skills/wren/SKILL.md`) and plugin metadata. Skill content lives in `core/wren/src/wren/skills_content/` | Claude plugin `wren` |
| `docs/core/` | Docusaurus pages (CC BY 4.0), copied to the docs-site repo by `sync-docs.yml`. `internals/` is not synced | docs.getwren.ai/oss |
| `examples/v5-jaffle/` | Golden `schema_version: 5` project, used by `core/wren` tests | — |
| `evals/spodbtify_ab/` | Agent A/B eval (schema-only vs dbt-integrated). The dataset is not in the repo | — |

Gone from this branch: `wren-ui/`, `wren-ai-service/`, `wren-launcher/`, `ibis-server/`
(archived on branch `legacy/v1`, tag `v1-final`). The allow rules for them in
`.claude/settings.json` are leftovers.

## How the pieces depend on each other

```
wren-manifest-macro → wren-core-base → wren-semantic-core ─┬→ wren-core-py ─(PyPI)→ wrenai ─(PyPI)→ wren-langchain / wren-pydantic
                                                           └→ wren-core-wasm ─(npm)→ GenBI apps
```

- Rust-to-Rust links are **path** dependencies, so a change in `wren-core-base` is seen
  right away by wren-core, wren-core-py and wasm.
- `core/wren` uses the **PyPI** wheel locked in `core/wren/uv.lock` (`wren-core-py`
  0.8.1). It doesn't see a local Rust change until `just use-local-core` builds and
  overlays the wheel (needs Rust and maturin). `wren-ci.yml` does build wren-core-py from
  the PR's own Rust and overlays it.
- The SDKs require `wrenai>=0.13.1` from PyPI, not the `core/wren` in this tree. Their CI
  tests against the published wrenai.
- GenBI apps load wasm from the CDN at the version pinned in
  `core/wren/src/wren/genbi/composer.py` (0.4.1).
- Releases are automated, and version numbers are owned by release-please. Never bump
  `Cargo.toml`, `pyproject.toml`, `uv.lock` or `__init__.py` versions by hand.
  (`core/wren-core-py/Cargo.toml` says `0.1.0`; that is a placeholder rewritten at
  publish time.) The cascade:
  1. The three Rust crates release together (linked group `wren-rust-core`) and
     `publish-wren-crates.yml` publishes them.
  2. `release-bindings-after-core.yml` opens `fix(bindings): build against wren-core X`,
     which relocks py and wasm.
  3. The py and wasm release PRs follow; `publish-wren-core-py.yml` builds the wheels.
  4. `sync-wren-core-py-lock.yml` opens `chore(wren): bump wren-core-py`.
- A new Rust capability (a new `DataSource`, say) reaches `core/wren` users only after
  that whole cascade.

## Commands in this cloud container

Verified on 2026-10-16.

| Present | Missing |
|---|---|
| `cargo`/`rustc` 1.97 stable (clippy, rustfmt), `uv` 0.11, `ruff`, Python 3.13, Node 22, npm, pnpm, docker CLI | `taplo`, `wasm-pack`, `cargo-insta`. `maturin` arrives with `uv sync` in `core/wren-core-py` |

Other limits:

- `just` is not preinstalled; `uv tool install rust-just` adds it (checked).
- The Docker daemon is not running, so testcontainers-based tests cannot run.
- The network policy blocks `extensions.duckdb.org`.
- `uv sync` picks Python 3.13, but CI uses 3.11. `requires-python >=3.11` allows both.

| Task | Command (run from the module dir) | Result here |
|---|---|---|
| Install `core/wren` | `uv sync` (= `just install`) | about 35 s |
| `core/wren` unit tests, same set as CI | `just test-unit`, or `uv run --no-sync pytest tests/unit/ --ignore=tests/unit/test_memory.py --ignore=tests/unit/test_mcp_server.py` | 1541 passed, 3 skipped, about 50 s |
| `core/wren` lint | `just lint` (`ruff format --check src/` + `ruff check src/`) | clean |
| `core/wren` format | `just fmt` | — |
| wren-core compile check | `cargo check -p wren-semantic-core --lib` | about 3 min cold, about 600 MB `target/` |
| wren-core unit tests | `RUST_MIN_STACK=8388608 cargo test -p wren-semantic-core --lib` | 162 passed. About 5 min cold build; `target/` grows to about 5 GB |
| Full Rust CI set | `RUST_MIN_STACK=8388608 cargo test --lib --tests --bins` | not run (long) |
| One sqllogictest file | `RUST_MIN_STACK=8388608 cargo test -p wren-sqllogictest --test sqllogictests -- <name-substring>` (append `--complete` to rewrite expectations) | not run |

These fail here because of the container, not the code:

- `just test` (= `pytest tests/`) stops at collection. `tests/connectors/test_postgres.py`
  imports `psycopg` at module level, so it needs `uv sync --extra postgres`, and its
  containers need Docker.
- `tests/suite/test_ref_sql.py` errors: DuckDB tries to download the `tpch` extension.
- The Docker-backed connector tests: postgres, mysql, starrocks, canner, clickhouse,
  trino, mssql.

`RUST_MIN_STACK=8388608` is required. Deep plan recursion in debug builds overflows the
default 2 MiB test-thread stack, TPC-H included.

## What CI actually runs

| Workflow | Triggers on | Runs |
|---|---|---|
| `wren-ci.yml` | PRs touching `core/wren/**`, `core/wren-core/**`, `core/wren-core-py/**`, `core/wren-core-base/**` | lint (`uvx ruff`, unpinned); `test-unit`; connector matrix of **postgres, mysql, starrocks only**; `test-ui` (`--extra ui`: `test_profile_web.py`, `test_field_registry.py`); `test-memory` (all of it, including slow); memory-onnx; embedding parity; `test-mcp` |
| `rust.yml` | `core/wren-core/**` (PRs and pushes to main) | `cargo check --all-targets`; `RUST_MIN_STACK=8388608 cargo test --lib --tests --bins` followed by `git diff --exit-code`; clippy `-D warnings`; `taplo format --check` |
| `core-py-ci.yml` | `core/wren-core-py/**`, `core/wren-core/**` | `cargo test`, `maturin develop`, `pytest` on Python 3.11 |
| `wasm-ci.yml` | wasm, `core/wren-core/core/**`, `core/wren-core-base/**` | wasm-pack build, dist, typecheck, **gzip size ≤ 15 MB**, `npm test` |
| `sdk-{langchain,pydantic}-ci.yml` | `sdk/<pkg>/**` | ruff; pytest on 3.11 and 3.12; build |

`rust.yml` has no `cargo fmt --check`. Run `cargo fmt` anyway.

CI never runs the following, so a test placed only here proves nothing to reviewers:

- `core/wren` connector tests for duckdb, datafusion, snowflake, canner, clickhouse,
  trino and mssql.
- `core/wren/tests/suite/`, and the root-level tests `tests/test_profile.py`,
  `test_profile_cli.py` and `test_cli_memory_detection.py`.
- `core/wren-core-base`'s own `cargo test`. No workflow runs it.
- The `#[wasm_bindgen_test]` tests in `core/wren-core-wasm/src/lib.rs`.

Also: `examples/v5-jaffle/` is not in `wren-ci.yml`'s paths, so editing only the fixture
triggers no test run even though tests read it.

## Change playbooks

**New data source.** Use commit `4e1c25e` (StarRocks) as the template; it touches every
layer:
1. Rust:
   - `core/wren-core-base/manifest-macro/src/lib.rs` (`data_source!`)
   - `core/wren-core-base/src/mdl/manifest.rs`
   - `core/wren-core/core/src/mdl/dialect/inner_dialect.rs`
2. `core/wren-mdl/mdl.schema.json`: the `dataSource` enum, edited by hand.
3. `core/wren/src/wren/`:
   - `model/data_source.py`, `model/__init__.py` (ConnectionInfo), `model/field_registry.py`
   - `connector/<x>.py` and `connector/factory.py` (`_REGISTRY`, `_INSTALL_EXTRA`)
   - `mdl/cte_rewriter.py` `_SQLGLOT_DIALECT_MAP`, when the sqlglot dialect name differs
     from the enum name
   - `dbt.py`, `context.py`, and the extra in `pyproject.toml`
4. Tests and tooling:
   - the marker in `tests/conftest.py`
   - `tests/connectors/test_<x>.py`
   - unit tests (`test_connector_factory.py`, `test_cte_rewriter.py`, …)
   - a `justfile` recipe
   - the `wren-ci.yml` matrix, if it should run in CI
5. Docs: `docs/core/guides/connect.md`, `docs/core/reference/mdl.md`,
   `core/wren/README.md`.

**MDL manifest field.** The structs are not written out in `manifest.rs`. Each one
(`Manifest`, `Model`, `Column`, `Relationship`, `View`, `Cube`, `Measure`, the RLAC/CLAC
types, `DataSource`) is a proc macro in `core/wren-core-base/manifest-macro/src/lib.rs`.
`src/mdl/manifest.rs` expands each macro twice: `(false)` for plain Rust and `(true)` for
the PyO3 classes.
- Add the field in the macro and give it a `#[serde(default)]` so old manifests still
  parse.
- Then update `src/mdl/builder.rs`, `core/wren-core-py` (`src/manifest.rs`, Python
  tests), `core/wren-mdl/mdl.schema.json`, the YAML↔MDL conversion in
  `core/wren/src/wren/context.py`, and `docs/core/reference/mdl.md`.
- `Manifest` holds `layoutVersion`, `catalog`, `schema`, `models`, `relationships`,
  `views`, `dataSource` and `cubes`. There is no `Metric` type.

**CLI command or flag.** The root app is in `core/wren/src/wren/cli.py`; sub-apps are in
`*_cli.py`.
- `tests/unit/test_served_content_guard.py` fails when `skills_content/`,
  `ask_templates/` or `skills/wren/SKILL.md` mention a `wren …` command or flag that
  doesn't exist. Update those texts when you rename or remove one.
- Also update `docs/core/reference/cli.md`, `core/wren/docs/cli.md` and
  `core/wren/.claude/CLAUDE.md`.

**Agent skill.**
- Content goes in `core/wren/src/wren/skills_content/<name>/SKILL.md`, plus optional
  `references/` and `scripts/`.
- It ships as wheel package-data and is served by `wren skills list|get`.
- Add a test in `tests/unit/test_skills_cli.py`.
- Don't add content under root `skills/` (see `skills/AUTHORING.md`).

**Engine behaviour (Rust).**
- Tests go in `core/wren-core/core/src/mdl/mod.rs`. Snapshots are inline
  (`assert_snapshot!(x, @"…")`); there are no `.snap` files. Or add an `.slt` case under
  `sqllogictest/test_files/`.
- To check the change from Python, build wren-core-py, then run `just use-local-core` in
  `core/wren`.

## Code gotchas

`core/wren`:
- `$WREN_HOME` (default `~/.wren`) is read at import time, separately in `cli.py`,
  `profile.py`, `context.py`, `cloud.py` and `memory/cli.py`. Tests monkeypatch those
  module globals (`profile._WREN_HOME`, `_PROFILES_FILE`, `cloud._CLOUD_FILE`, …), not
  the env var.
- `.env` files (cwd, project root, `~/.wren/.env`) are merged into `os.environ` once per
  process, and `${UPPER_VAR}` in a profile is expanded at connect time. Tests reset this
  with `profile._reset_env_loaded_for_tests()`.
- `wren.mdl.get_session_context` is `@lru_cache(maxsize=32)`. Never mutate the returned
  context; tests call `cache_clear()`.
- CLI startup must stay light. `tests/test_cli_memory_detection.py` asserts that
  `wren.cli` imports neither lancedb nor torch. Import heavy or optional deps inside
  functions, marked `# noqa: PLC0415` (ruff selects `PLC`). `mcp_server.py` imports `mcp`
  at module level, so import it only after `serve_cli` has checked the extra.
- Project discovery order: `--path`/`--project`, then `WREN_PROJECT_HOME`, then a walk up
  from cwd for `wren_project.yml` (stops at `$HOME`), then `default_project` in
  `~/.wren/config.yml`.
- Profile choice: a `profile:` pin in `wren_project.yml` wins; otherwise the active
  profile in `profiles.yml`.
- When `strict_mode` or `denied_functions` is set, failing to scope the sub-manifest is a
  hard `INVALID_SQL`. Otherwise it quietly falls back to the full manifest.
- Extras: `main` = `interactive` + `ui`, without memory. `all` = connectors + `main` +
  `memory` + `mcp`, without `memory-onnx`.
- Validation boundary (from the module guide): no `isinstance` guards downstream of
  wren-core's deserialization. Validate only real inputs: user JSON/YAML, API responses.

Rust:
- `transform_sql` is synchronous and errors when called inside a Tokio runtime. Use
  `transform_sql_with_ctx` in async code.
- `logical_plan/analyze/model_anlayze.rs`: the typo is the real filename.
- `rustfmt` uses `max_width = 90` in wren-core and wren-core-py, and the default 100 in
  base and wasm.
- Two sqlparser versions are in the tree: base pins 0.58, and DataFusion brings 0.62,
  which `wren_core` re-exports. Don't mix their types.
- wasm is kept outside the workspace because of feature unification: workspace members
  turn on `tokio/rt-multi-thread` and DataFusion default features, which don't build
  for wasm32. Keep `default-features = false` there.

## Known stale statements in upstream docs

| Where | Says | Reality |
|---|---|---|
| `.claude/CLAUDE.md`, README | "PyPI: wren-core", "npm: wren-core-wasm" | `wren-core-py`; `@wrenai/wren-core-wasm` |
| `.claude/CLAUDE.md` | skills are `wren-generate-mdl, wren-usage, …` | one stub `skills/wren`. Content: `onboarding`, `usage`, `generate-mdl`, `dlt-connector`, `enrich-context`, `genbi` |
| `.claude/CLAUDE.md` | `examples/` is a placeholder; no mention of `sdk/` or `evals/` | see the map above |
| `.claude/CLAUDE.md`, wren-core and base guides | a `sql/` module; a `Metric` type; types defined in `manifest.rs` | neither exists; types are proc macros in `manifest-macro/src/lib.rs` |
| `.claude/CLAUDE.md` | wasm `just test` is wasm-pack test; binary ~68 MB | `node --test` on `dist/`; ~57 MB raw / ~14 MB gzip |
| `.claude/CLAUDE.md`, wren-core-py guide | "Ibis / sqlglot", "ibis-server" | no ibis anywhere. sqlglot `CTERewriter` in `core/wren/src/wren/mdl/cte_rewriter.py` |
| `.claude/CLAUDE.md` | CI triggers only on changes inside the module | several workflows also watch upstream modules (see the CI table) |
| `core/wren/.claude/CLAUDE.md` | `cd wren`; `_transpile()`; only canner and file sources are remapped | `core/wren`; `CTERewriter.rewrite`; mssql→`tsql` and datafusion→`wren` are mapped too |
| `core/wren/.claude/CLAUDE.md` | extras and command lists | also extras `memory-onnx`, `interactive`, `ui`, `mcp`, `main`; also commands `wren --sql …` (default form), `--version`/`-V`, `wren cloud git-credential get\|store\|erase` |
| wren-core-wasm guide | it's a separate crate because wren-core uses the Canner fork | both use upstream DataFusion 55 |
| wren-core-py guide | `--no-default-features` disables extension-module linking | `extension-module` is hard-coded in the pyo3 dependency |
| `core/wren/README.md`, `core/wren/docs/cli.md`, `docs/core/reference/cli.md` | `schema_version: 2`; `main` includes memory; memory lives in `~/.wren/memory/` | 5; it doesn't; `<project>/.wren/memory/`, falling back to `~/.wren/memory/` |
| `.github/labeler.yml`, CONTRIBUTING | `sdks/**` paths | the directory is `sdk/`, so the sdk labels never apply |
| `core/wren-mdl/mdl.schema.json` `$id` | `…/main/wren-mdl/…` | the file lives at `core/wren-mdl/` |
