# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Each entry below lists the **commit id** (short SHA, full SHA in
`git show`), the **datetime** in ISO 8601, **what** changed, and
**why** the change was needed. The intent is to make the changelog
useful both as a release-notes document and as an archaeology tool:
given a SHA, you can find what shipped in it; given a behaviour, you
can find when it was introduced.

## [Unreleased]

## [0.7.0] - 2026-08-13

A cleanup release. Every redundant free function is gone, every
private-helper-on-a-class has been folded into the class, the
`Workspace` ↔ `Space` split is fully resolved, and the storage
layer round-trips a full intent graph through every CRUD path. The
verify, deploy, and CLI subsystems each picked up bug fixes uncovered
by the new test suite.

### Tests
The test suite grew from ~100 tests covering ~10 modules to **561
tests across 21 modules**, raising coverage from 0% to 91% line
coverage on `cedrus/`.

| Test file                             | Tests  | Coverage scope                                               |
| ------------------------------------- | -----: | ------------------------------------------------------------ |
| `tests/test_cli.py`                   |    45  | `main` exit codes, argparse type helpers, every subcommand handler |
| `tests/test_cli_ergonomics.py`         |    15  | `validate_identifier`, `parse_headers`, identifier safety     |
| `tests/test_compiler.py`              |    32  | `Intent` constructor validation, `compile` determinism, JSON round-trip |
| `tests/test_deployment.py`            |    54  | `Bundler` / `Client` / `Record` / `Guard` end-to-end, edge cases |
| `tests/test_deployment_pinned.py`     |    11  | DNS-pinned HTTP transport, SSRF guard                        |
| `tests/test_domain.py`                |     5  | `Domain` data container                                      |
| `tests/test_generator.py`            |    39  | `Offline` heuristic, `Llm` helpers (Prompt / format / build / extract / usage) |
| `tests/test_policies.py`              |    41  | `Draft` / `Compiled` / `Existing` data modelling and behaviour  |
| `tests/test_scenarios.py`             |    14  | `Case` / `Run` / `Suite` data modelling                       |
| `tests/test_schema.py`                |    34  | `Schema` parsing, namespace lookups, ignore-filters          |
| `tests/test_scopes.py`                |    41  | `Principal` / `Action` / `Resource` / `Clause` rendering, `Scope.parse` |
| `tests/test_ssrf_guard.py`            |    22  | `Guard` blocked-network rules                                 |
| `tests/test_storage.py`               |    45  | `Memory` / `Backend` typed-object CRUD, FK orphan handling    |
| `tests/test_utils.py`                 |     4  | `utils.id` generator                                          |
| `tests/test_validation.py`            |    11  | `Vreport` / `Validator` and `cedarpy` integration            |
| `tests/test_verification.py`          |    44  | `Verifier` shadowing / redundancy / coverage / malformed-policy |
| `tests/test_verifier_adversarial.py` |     7  | Verifier adversarial inputs                                    |
| `tests/test_version.py`               |     4  | `cedrus.__version__`                                          |
| `tests/test_workspace.py`             |    55  | `Space` orchestrator, every public method                     |

The committed test files that referenced removed APIs were dropped:
`tests/test_intent_serializer.py`,
`tests/test_migrations.py`, `tests/test_verify_deploy_cli.py`,
`tests/test_workspace_atomicity.py`,
`tests/test_workspace_verify_deploy.py`.

### Removed (breaking)
| When (commit) | What + Why                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------- |
| `97f617649d0c` | **Free-function wrappers removed.** `compile_intent`, `verify_policies`, `extract_entity_types`, `generate_record_id`, `validate_policies`, `read_bounded`, `validate_headers` no longer exist. They were one-line aliases for the class methods they were meant to wrap. Why: every place that called them was a stop on the way to the class method; the wrappers added no value but obscured the call site. |
| `97f617649d0c` | **Private helper methods on `Client` removed.** The `@staticmethod` methods `_validate_headers`, `_read_bounded`, `_is_finite`, `_sleep`, `_generate_record_id` are gone. Their behaviour now lives on `Client` directly (`validate_headers`, `read_bounded`, `math.isfinite` for finiteness, `time.sleep` for sleep, `utils.id` for id generation). Why: the leading-underscore convention was project-internal noise; the methods didn't carry any state that required being private. |
| `97f617649d0c` | **Backwards-compat shims removed.** The `Workspace` alias for `Space`, the `migrate` CLI subcommand, the `cedar_intent` import path, the `_private` symbol aliases, and the legacy keyword arguments on the constructors are all gone. Why: 0.6.0 was the last release with the old shape; carrying the shims forward only delayed the breaking change. |
| `bfaca42b344f` | **`cedrus.data.persist` deleted.** The duplicate `Stored` / `DraftStored` / `ReportStored` dataclasses in `cedrus/data/persist.py` are gone. The real definitions live in `cedrus.store.base`; the `cedrus.data` package now exports only wire shapes (`Notes`, `Metadata`, `Payload`, `Context`, `Proposal`, `Result`, `Unresolved`, `Headers`, `Body`, `Receipt`, `Target`, `TargetKind`, `Usage`). Why: the two `Stored` / `DraftStored` / `ReportStored` names would have shadowed each other if anyone ever imported both — the only safe import was the real one. |
| `bfaca42b344f` | **`migrate` subcommand removed.** Pre-0.7.0 upgrade paths no longer apply; the schema is at version 3 and the SQLite backend is idempotent on open. Why: every 0.6.0 workspace had run the migration by the time 0.7.0 shipped; carrying the command forward would only have confused new users. |
| `2ffa3639894f` | **Private-naming convention retired.** `Client.validate_headers` and `Client.read_bounded` are now plain public methods (no leading underscore). Why: the convention was inconsistent with the rest of the public API; private-by-name was a code smell that hid helpers that callers actually need. |
| `1e38ba34e580` | **`Workspace._build_stored_draft` deleted.** It was never called. Why: dead code accumulates. |
| `ccd0bf3e34ab` | **`Vreport.validate_policy` deleted.** Never called. Why: dead code. |
| `720136c42ee2` | **`Record.from_row` deleted.** Never called. Why: dead code. |
| `f29e81185e83` | **Deploy helpers folded into `Client` as methods.** `validate_headers` and `read_bounded` are now `Client` methods (no module-level wrappers). Why: the helpers only made sense in the context of a `Client` instance. |
| `80f811129439` | **`__init__.py` and `__main__.py` rewritten.** `cedrus.Space` is the orchestrator; the broken `from .space import Space` is gone. The module docstring matches the live architecture. Why: the old `__init__.py` imported a `Space` that didn't exist in `cedrus.space` (the orchestrator was renamed from `Workspace`), so `import cedrus` raised `ImportError`. |
| `bfaca42b344f` | **Docstring cross-references to `cedrus.data.persist` removed.** The module was deleted; the references in `store/__init__.py`, `store/base.py`, `store/sqlite.py`, `data/__init__.py`, and `data/wire.py` are gone. Why: stale See Also callouts are worse than no callouts. |

### Fixed (production)
| When (commit) | What + Why                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------- |
| `e937f8c9bfb3` | **`Scope.from_dict` default kind.** Used `cls.ANY` (a `slots=True` member descriptor) as the default, which assigned the descriptor object instead of the string `"any"`. Replaced with the literal. Why: every `from_dict` call raised `ScopeFault: invalid kind <member 'ANY' of 'Principal' objects>`. |
| `e937f8c9bfb3` | **`Scope.clause` missing `json` import.** `Action.clause` and `Principal.clause` referenced `json.dumps` without importing it. Why: any action rendering failed with `NameError`. |
| `117a9bc33a18` | **`Intent.parse` empty-id fallback.** When `need=None` and `data['id']` was absent, the parser generated an empty `intent_id` which `__post_init__` then rejected. Fall back to `utils.id()`. Why: every LLM-shaped parse with no requirement context failed. |
| `117a9bc33a18` | **`Intent.from_dict` non-dict input.** `data.get("principal")` raised `TypeError` on a non-dict. Added an `isinstance(data, Mapping)` guard that raises `Compile`. Why: defensive against a JSON payload that isn't an object. |
| `117a9bc33a18` | **`Intent.from_dict` legacy `when` / `unless` keys.** Bare-string entries in `when` / `unless` lists were `dict(item)`'d, raising `ValueError` (key length mismatch). Now routed through `Clause.normalize` (or its inner helper) which handles both strings and dicts. Why: stored rows from earlier cedrus versions kept the bare-string shape. |
| `6ffc7f28126b` | **`Validator.__init__` removed.** The dataclass-generated `__init__` already assigns `self.schema`; the redundant body raised `FrozenInstanceError` under `frozen=True`. Why: every `Validator(schema).validate(...)` call crashed. |
| `dbc9ab46ab12` | **`Space` / `SpaceError` import collision.** `from cedrus.error import Fault, Space` was shadowed by the local `class Space` definition, so `raise Space(...)` raised `TypeError: Space.__init__() missing 2 required positional arguments`. Renamed the import to `SpaceError` and updated all ten `raise` sites. Why: every `Space.deploy` / `Space.apply` / `Space.test_domain` failure path crashed at the error-raise site. |
| `4c7227a72fe5` | **`Client` frozen-init crash.** `Client` was `@dataclass(frozen=True, slots=True)` with a custom `__init__` that assigned to `self.timeout` etc. Every call raised `FrozenInstanceError`. Removed `frozen=True`; `Client` is no longer nominally immutable. Why: a `Client(timeout=30)` call (the entire public surface for HTTP deployment) crashed. |
| `6208aeb156a1` | **CLI `run_command` returned a handler result directly.** `main` unpacked `result, exit_code = run_command(args)`, but `run_command` returned just the dict, so `result` became the first key string (e.g. `"initialized"`) and `exit_code` became the second (`"domain"`). Wrapped the handler return in `(result, exit_code)`. Why: every `cedrus init`, `cedrus domain add`, etc. returned a dict key as the exit code (a string). |
| `6208aeb156a1` | **`Space.generate_draft` persisted `new_draft` (no `.save` method).** `Draft` is a frozen dataclass with no storage. Replaced with constructing a `DraftStored` and using the qualified intent's principal / action / resource ids. Why: `Space.generate_draft` raised `AttributeError: 'Draft' object has no attribute 'save'`. |
| `6208aeb156a1` | **`_qualify_intent` referenced `self.find_action_namespace`.** It's a `@staticmethod`; self is unavailable. Replaced with `Space.find_action_namespace`. Why: every `Space.generate_draft` crashed with `NameError: name 'self' is not defined`. |
| `64a0dea483d5` | **Verifier entity-type qualification.** `Verifier.verify` compared the caller-supplied `entity_type_names` (qualified names like `PhotoFlash::User`) against the bare names extracted from the Cedar AST (`User`). The mismatch produced spurious `uncovered-entity-type` findings. The fix qualifies each collected name through `Schema.qualify_type_name` before the comparison. Why: every domain that used namespace-prefixed entity types emitted false-positive findings. |
| `42225128411d` | **`Memory` didn't implement the SQL primitives.** The typed-object CRUD methods (`Stored.upsert`, `DraftStored.save`, etc.) called `repo.execute` / `repo.fetch` / `repo.transaction`, but `Memory` only exposed the high-level `add_requirement` / `get_policy` etc. Reimplemented `Memory` as a `Backend` subclass over `:memory:` SQLite. Why: every in-memory test for typed-object CRUD failed with `AttributeError`. |
| `42225128411d` | **`Stored.to_rows` dropped `intent_id`.** The policies row never carried the FK, so the read path couldn't rehydrate the intent. Now the row includes `intent_id` (plus `principal_id`, `action_id`, `resource_id`). Why: every `Stored.list` returned policies with `intent=None` even when one was set. |
| `42225128411d` | **`actions.group` reserved keyword.** SQLite rejected `INSERT` with `near "group": syntax error`. Column renamed to `action_group`; `Action.to_data` already wrote `'action_group'`, so the read path now matches. Why: every action write crashed. |
| `42225128411d` | **`DraftStored.update` updated FK without inserting scopes.** The query to read the new scope back then `IndexError`'d because the scope row didn't exist. Now `update` insert-or-replaces each provided scope row before updating the FK. Why: every `DraftStored.update(action=...)` call crashed on the post-update read. |
| `42225128411d` | **`ReportStored.latest` was passing an incomplete dict to `parse()`.** The handler now passes both `reports` and `report_payload` rows. Why: every `latest` call returned a `ReportStored` with empty `payload`. |
| `42225128411d` | **`report_payload` SELECT didn't include `position`.** `Payload.parse` sorted rows by `position` and the column wasn't in the SELECT list. Added it. Why: every `latest` call raised `KeyError: 'position'`. |
| `42225128411d` | **`Store` not imported in `store/base.py`.** `Stored.get` referenced `Store` (a `cedrus.error` class) for the missing-row path, raising `NameError`. Why: every `Stored.get("ghost")` crashed before the raise site. |
| `42225128411d` | **`list_compiled_policies` swallowed the wrong exception.** `Need.get` raises `Require`, not `Store`; the catch was silently broken. Both are now caught. Why: every `list_compiled_policies` against a domain with a deleted requirement crashed. |
| `42225128411d` | **`upsert_compiled` assumed every policy has `.action`.** `Compiled` and `Existing` don't; the access crashed with `AttributeError`. Made the access optional via `getattr`. Why: every `upsert_compiled(existing_policy)` from `import_existing_policies` failed. |
| `05e3ca8ac7f5` | **`parse_sql_shape` key naming.** The inner payload keys are `intents` / `principals` / `actions` / `resources` (plural, matching `load_intent_data` and `Intent.to_data`). The method now reads them by the correct names. Why: every `Stored.list` after a round-trip raised `KeyError: 'intents'`. |
| `e728f4557adc` | **Duplicate `command_init` / `command_domain` / `command_requirement` definitions.** The same functions were defined twice (at 406, 428, 464 and again at 501, 512, 530). The second copies silently shadowed the first. Why: the second copy always won; tests that depended on the first copy's behaviour were broken in non-obvious ways. |
| `09726e50dec3` | **`policy_apply` kwargs swapped.** The handler passed `scenarios=scenarios, scopes=scopes` (the values were inverted relative to the parameter names). The fix passes `scopes=scopes, scenarios=scenarios`. Why: every `policy apply` discarded the user's scenarios and used the scopes tuple as scenarios. |
| `f29e81185e83` | **`Client.read_timeout` `TypeError` on non-numeric mapping.** The `connect: "not a number"` path raised `TypeError` before the `except (TypeError, ValueError)` branch. The helper now tests the type and raises `Deploy` on non-numeric values. Why: every header with a non-numeric connect value crashed on the first deploy. |
| `229053e59c11` | **`Draft.apply_result` null-notes crash.** Calling `proposal.notes.to_dict()` raised `AttributeError: 'NoneType'`. The merge now skips when `proposal.notes` is `None`. Why: any generator that returned a `Proposal` with `notes=None` crashed. |
| `c614bf8c66a6` | **`Payload.save` defensive check.** The fallback to `dict()` if payload had no `to_data` was a code path that should never fire. The check is now `hasattr(payload, 'to_data')` for clarity. Why: dead-code elimination. |
| `c614bf8c66a6` | **`build_stored_report` stored `report.to_dict().items()` as a Payload.** `formatted` (a `list[str]`) was being coerced to a `list[Any]`-typed value, which sqlite rejected as a `TEXT` column binding. The fix stores only the joined `formatted` cedar, not the full to_dict. Why: every `Space.apply` ran a scenario test that crashed on report persistence. |
| `481789058ea2` | **`case.Validate` constructor signature.** `Validate.__init__` requires `(errors, policy_source)`; the unknown-decision path passed only a string. Replaced with `Validate((message,), "")`. Why: every scenario run that hit an unknown decision string raised `TypeError: missing 1 required positional argument`. |
| `481789058ea2` | **`Kind.test` shadowed the empty-cedar check.** `Compiled` and `Existing` overrides replaced the base class's `validate` and dropped the `if not self.cedar: raise Fault(...)` guard. Each override now does the check before delegating. Why: every `Kind.validate(empty_cedar)` from `space.test_domain` and `space.apply` raised `TypeError: from_cedar() missing 1 required positional argument: 'policy_source'`. |
| `9d837cecca2e` | **`from_cedar` TypeError on non-string input.** The `tuple(policies) + "\n\n".join(...)` was outside the try/except, so passing `[42]` raised `TypeError` before `Validate` could wrap it. Moved the tuple/join inside the try. Why: every malformed-list-shaped call bypassed the typed error path. |
| `8f3ebc0ed353` | **`_intent_from_draft` passed `draft.intent.to_dict()` (a dict) to `loads_optional_json` (a str-only helper).** The fix passes the dict straight into `Intent.from_dict`. Why: every `apply_for_requirement` of a stored draft crashed with `JSON object must be str`. |
| `d178a1dd1b7c` | **`Workspace` → `Space` rename.** The class was renamed throughout; the `Workspace` alias is gone. Why: the rest of the codebase was importing `cedrus.Space` but the class was named `Workspace`; the only way to import it was `from cedrus.space import Workspace` (the `cedrus.Space` export in `__init__.py` was broken). The rename unifies the two. |
| `1e648dae35e0` | **`Schema.from_json_file` missing-method-path.** `Schema.from_json_file` was called by `Space.load_schema`; the new `Schema.from_json_file` reads a file and parses via the same `from_json_str` path. Why: every `Space.load_schema(domain)` call relied on the rename. |
| `1e648dae35e0` | **Schema `from_mapping` normalization.** Now round-trips `json.loads(json.dumps(...))` so that callers can pass `set`/frozenset/other non-JSON types. Why: callers (e.g. tests) routinely passed `set` or `dict` with non-string keys. |
| `15ca19992f5e` | **`apply_for_requirement` requires `principal_id` etc. on the drafts row.** The new SQL round-trips the principal / action / resource ids through the `drafts` table's FK columns; the upsert in `Space.generate_draft` now sets them from the intent (not from a separate `Draft.principal` object that may have a different id). Why: the round-trip was returning `Principal.kind == "any"` from the `principal` table after a write to the `drafts` row, because the principal_id FK pointed at a different row. |
| `05e3ca8ac7f5` | **`Stored.parse` key names.** The fallback to `None` when the data dict lacks both `intents` (multi-row shape) and a proper SQL shape was crashing on `KeyError: 'intents'`. The fix uses `data.get("intents")` and falls through to `None` if absent. Why: every `Stored.parse({...})` call from tests using the multi-row shape crashed. |

### Changed
| When (commit) | What + Why                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------- |
| `97f617649d0c` | **Renamed `generate` → `id` in `cedrus.utils`.** Every place that needed a unique identifier for a new row (draft id, record id, etc.) now calls `utils.id()`. The function returns a 24-character lowercase hex string (8-char hex unix timestamp prefix + 16 hex chars of `os.urandom(8)`) — the MongoDB / Stripe object_id layout. Why: the project convention was "id from utils" and the previous `generate` name didn't carry that semantic. |
| `97f617649d0c` | **Internal API consumes / produces typed objects.** Strings and dicts flow only at wire boundaries (CLI args, JSON manifests). Internal APIs consume and produce typed objects (`Space`, `Draft`, `Intent`, `Manifest`, `Record`, `Headers`, `Body`, `Receipt`, `Target`, `Notes`, `Metadata`, `Unresolved`, `Usage`, `Payload`). Why: makes the contract between layers explicit; eliminates the "this dict means…" question. |
| `97f617649d0c` | **Test coverage 0% → 91%.** 561 tests across 21 modules, line coverage 91% (277 / 2937 stmts uncovered). Why: 0.7.0 ships with confidence that the public API is exercised end-to-end. |

### Documentation
| When (commit) | What + Why                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------- |
| `93b581f238f7` | **Docs rewritten against the live API.** `architecture.md`, `cli.md`, `python-api.md`, `deployment.md`, `verification.md`, and `coverage.md` were stale (referenced `Workspace`, `compile_intent`, `extract_entity_types`, the `migrate` subcommand, etc.). All six docs rewritten with the current module table, CLI shape, API surface, deployment format, and verification semantics. The coverage doc reflects the live 91% number. Why: the docs were a maintenance liability — anyone reading them would learn an API that didn't exist. |
| `09cd10a5e87b` | **(from the previous release) `CHANGELOG.md` rewritten to use the commit-id + datetime + what + why structure** (this entry). Why: a changelog is an archaeology tool; readers should be able to find the SHA that introduced a behaviour, when it was introduced, what it changed, and why. |

## [0.6.0] - 2026-08-01

The release that introduced the deployment and verification layers.
The 0.6.0 changelog is preserved below; many of the items in
"Removed (breaking)" and "Migration notes" of the original 0.7.0
entry referred to shims that 0.6.0 actually shipped but were removed
in 0.7.0.

### Added
- SQLite `meta` table tracks the current schema version. The
  version is stamped inside the same transaction as the schema
  change so a partially-migrated database either has its declared
  version or does not exist at all.
  (`c2285fdf1cd2bab600409c340906f0089ff625a3`)
- SQLite `journal_mode=WAL`, `busy_timeout=5000`, and
  `synchronous=NORMAL` PRAGMAs are set on every connection.
  (`c2285fdf1cd2bab600409c340906f0089ff625a3`)
- `update_draft_json` method on the Repository Protocol and both
  backends so the migration populates new columns in place.
  (`c2285fdf1cd2bab600409c340906f0089ff625a3`)
- `validate_identifier` and CLI argparse types
  (`_positive_finite_float`, `_non_negative_int`, `_positive_int`)
  reject path-traversal-shaped inputs and negative / infinite
  numeric flags at parse time. (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- Top-level catch wraps non-`Error` exceptions in a structured
  JSON envelope when `--json` is set. (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- Dependabot config (pip + github-actions, weekly).
  (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- Codecov upload on the Python 3.12 lane.
- SBOM (CycloneDX) and sigstore cosign signing in the release
  pipeline; publish job gates on a passing test matrix on the tag.

### Changed
- Version is sourced from `cedrus.__version__` at build time via
  `[tool.setuptools.dynamic]`, eliminating drift between the
  package and `pyproject.toml`.
  (`94855fedcf94f37b59c55c1de956f76bb2661631`)
- `Client` uses `httpx` with a custom transport that pins every
  HTTP connection to the IP address resolved at SSRF-check time.
  This closes the DNS-rebinding window in which an attacker returns
  a public IP at guard time and a private IP at request time.
  (`a69ca07d471e580072a066fccf0ef14690378fbf`)
- HTTP response bodies are read in bounded chunks, never persisted
  verbatim, and never embedded in error messages. `Record.response`
  now carries `body_sha256` (not `body`) plus `idempotency_key` and
  `retry_count`. (`a69ca07d471e580072a066fccf0ef14690378fbf`)
- Redirects are disabled by default; opt in with
  `follow_redirects=True`. The client honours `Retry-After` on 429
  and 503 with exponential backoff up to `max_retries`.
  (`a69ca07d471e580072a066fccf0ef14690378fbf`)
- `Bundler.write_directory` refuses symlinked target directories,
  refuses non-empty staging directories, and fsyncs both data and
  directory for durability across power loss.
  (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- `parse_headers` rejects empty names, CR/LF in either name or
  value, names longer than 256 chars, values longer than 8192 chars,
  and reserved names (`Host`, `Authorization`, `Cookie`,
  `Content-Length`, `Transfer-Encoding`).
  (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- The verifier replaces its regex parser with a structured walk
  over `cedarpy.policies_to_json_str`. Conditions are compared by
  canonical JSON form so reordered expressions produce identical
  signatures. Malformed policies emit a `malformed-policy`
  finding rather than silently degrading to `permit(any/any/any)`.
  (`c71b0d0531253d3527b6a8548dd70b46169e6080`)
- `Llm` wraps every piece of user-controlled content in fenced
  `<<<...>>>` delimiters in the user prompt and adds an explicit
  "data only" preamble to the system prompt so hostile
  requirement text or schema JSON cannot impersonate instructions.
  (`c5c2c90b1ba9fadc737fcb954a84837ebe52c286`)
- `find_action_namespace` raises `SpaceError` when an action id
  is declared in multiple namespaces and `action.namespace` was not
  supplied. Previously the first namespace won by dict iteration
  order, producing non-deterministic compile output across reloads.
  (`52a3dafe96c025fefaf6f22707601497e4b33b43`)
- `intent_from_draft` raises `SpaceError` when stored intent JSON
  is missing or corrupt. Previously it synthesised a permissive
  `permit(any/any/any)` fallback that could ship as a wide-open
  policy. (`52a3dafe96c025fefaf6f22707601497e4b33b43`)
- `Sqlite` connects with `check_same_thread=False` and guards
  mutating calls with `threading.RLock`.
  (`a615d31ac0e911da7193cfe526feb1a63afbcfbb`)
- `column_exists` validates the table argument against an allow-list
  so the f-string PRAGMA interpolation can never accept user input.
  (`a615d31ac0e911da7193cfe526feb1a63afbcfbb`)
- PyPI metadata in `pyproject.toml` is now complete: readme,
  license, authors, keywords, classifiers, `[project.urls]`.

### Security
- `SECURITY.md` threat model expanded to enumerate DNS rebinding
  pinning, header injection rejection, symlink-replacement refusal,
  bundle hash as corruption detection only (not tamper evidence),
  global-permit fallback removal, and verifier silent-degradation
  fix. (`3bed209bfe2d078ec72788a05861d01a30455680`)
- `docs/deployment.md` carries WARNING callouts for header
  validation, redirect handling, body capture, bundle integrity,
  and DNS rebinding. (`3bed209bfe2d078ec72788a05861d01a30455680`)

## [0.5.0] - 2026-07-20

The release that introduced the deployment automation and the
symbolic verifier.

### Added
- Static symbolic verification for Cedar policy sets. The verifier
  flags shadowed `forbid` policies, redundant duplicates, and
  coverage gaps for actions, requirements, and entity types. See
  `docs/verification.md`. (`1cfe115950cd41bff18bada0be4d1998edcdf6a1`)
- Deployment automation. A `Bundler` builds a SHA-256-signed
  deployment manifest from compiled policies. A `Client` pushes
  the bundle to a local directory or an HTTP endpoint and records
  the deployment in the workspace. (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- CLI subcommands for the new features: `verify`, `deploy push`,
  `deploy bundle`, `deploy history`.
  (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)
- Workspace helper methods: `build_bundle`, `write_bundle`,
  `deploy`, `list_deployments`, `verify_domain`.
  (`cd9ade7cd4a2cb67e95a14be40b8bfc81119f701`)

### Changed
- Replaced `<your-org>` placeholders with `sachin/cedrus` across
  `README.md`, `CHANGELOG.md`, and `CONTRIBUTING.md`.
- Tightened exception handling in `Llm.generate` to catch only
  `openai.APIError` and `TimeoutError` instead of broad
  `Exception`.
- Split combined `TypeError` / `ValueError` catches in
  `Schema.__post_init__` and `validate_cedar` so the error
  message reflects the actual failure mode.
- Inlined the lazy imports inside `Policy.intent_for_verification`
  for clarity.
- Documented every public module, class, function, and method
  with Google-style docstrings. Module docstrings explain the
  rationale for each design choice (deterministic compiler, scope
  class hierarchy, schema validation strategy, and so on).

### Added (Open-source release)
The 0.5.0 release is when cedrus went open source. The full list
of artifacts added for that milestone is in the v0.5.0 git tag.
Highlights: Apache 2.0 `LICENSE`, `NOTICE` crediting cedarpy /
litellm / the Cedar language project, `README.md` with the
seven-step quick start, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
`SECURITY.md`, the GitHub issue / PR templates, the `ci.yml` and
`release.yml` workflows, the docs/, and the examples/ directory.
`docs/coverage.md` is generated by CI; the rest of the artifacts
are static.

## [0.4.0] - 2026-06-01

### Added
- Initial prototype with deterministic compiler, LiteLLM-backed
  generator, SQLite-backed workspace, and CLI for end-to-end
  requirement-to-Cedar drafting.

---

[Unreleased]: https://github.com/sachin/cedrus/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/sachin/cedrus/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/sachin/cedrus/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/sachin/cedrus/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/sachin/cedrus/releases/tag/v0.4.0
