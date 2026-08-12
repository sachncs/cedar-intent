# cedar-intent → cedrus: 0.7.0 full rebuild plan

This document enumerates **254 atomic commits** that together rename the
package from `cedar_intent` to `cedrus`, enforce single-word naming,
build a polymorphic OOP architecture, and replace every string/dict
boundary with a typed object.

The plan targets Python 3.11+, ruff + mypy --strict, and 88% line
coverage.

---

## Conventions

### Naming

- **Single word everywhere**: filenames, classes, functions, methods,
  variables, constants. Multi-word compound names are replaced with
  single-word alternatives (e.g., `policy_id` → `id`).
- **No leading underscores**: even module-private symbols lose their
  underscore prefix. Internal scope is conveyed via `__all__` and
  module docstrings, not name prefixing.
- **No `Kind` suffix on enums tied to a class**: discriminator values
  are class-level constants on the owning class (e.g.,
  `Principal.IS_TYPE`). `Kind` is kept only on standalone enums
  (`TargetKind`, `ReportKind`) to disambiguate from the noun class.

### Polymorphism

- **Abstract base / Protocol** for every entity that has multiple
  implementations or whose concrete class should be subclassable
  (`Scope`, `Policy`, `Generator`, `Repository`).
- **Single concrete orchestrator class** per concept, with subclassing
  documented as the extension path (`Verifier`, `Validator`,
  `Bundler`, `Runner`, `Migrator`, `Client`, `Parser`, `Space`,
  `Cli`).
- **Interface Segregation**: the Repository is split into one Protocol
  per entity type (`NeedRepository`, `StoredRepository`,
  `DraftRepository`, `ReportRepository`, `DeployRepository`,
  `UnitOfWork`). Implementations use `@overload` for type dispatch.

### Encapsulation

- **Wire shapes**: `@dataclass(frozen=True, slots=True)` for true
  immutability.
- **Mutable state**: `@dataclass(slots=True)` for `Domain`. Mutation
  funnels through `Domain.mutate(**changes)`.
- **Orchestrators**: plain class with `__init__` storing config; all
  behavior via methods; state is read-only after construction.

### Object flow

- Strings and dicts flow only at wire boundaries (HTTP body, SQLite
  column JSON, manifest JSON).
- Every internal API takes and produces typed objects.
- `dict` returns are produced only by `.to_dict()` methods on wire
  shapes.

---

## Phase A — Bootstrap (4 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 1 | `chore(release): introduce 0.7.0 with full rebuild` | `CHANGELOG.md`, `cedar_intent/__init__.py` | CHANGELOG has `[0.7.0] - Unreleased` section; `__version__ = "0.7.0"` |
| 2 | `chore(build): rename pyproject.toml distribution cedar-intent → cedrus` | `pyproject.toml` | `name = "cedrus"`; `[project.scripts] cedrus = "cedrus.cli:main"`; `[tool.setuptools.dynamic] version = {attr = "cedrus.__version__"}`; `[tool.setuptools.packages]` lists `cedrus.*`; `[tool.setuptools.package-data] cedrus = ["py.typed"]` |
| 3 | `chore(rename): move package directory cedar_intent → cedrus` | `cedar_intent/` → `cedrus/` (git mv) | `cedrus/` exists; `cedar_intent/` does not |
| 4 | `chore(rename): replace internal imports cedar_intent → cedrus` | all `.py` files in `cedrus/`, `tests/`, `examples/` | Zero references to `cedar_intent` (string or symbol) remain in `.py` files; `python -c "import cedrus"` succeeds |

---

## Phase B — Class renames (53 commits)

### Error hierarchy (11 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 5 | `refactor(error): rename CedarIntentError → Error` | `cedrus/error.py`, `__init__.py`, all import sites | All references updated; `tests/test_errors.py` updated |
| 6 | `refactor(error): rename ConfigError → Config` | `cedrus/error.py`, all import sites | `Config` subclass of `Error`; tests reference `Config` |
| 7 | `refactor(error): rename RequirementError → Require` | `cedrus/error.py`, all import sites | `Require` subclass of `Error` |
| 8 | `refactor(error): rename PolicyError → Policy` | `cedrus/error.py`, all import sites | `Policy` subclass of `Error` |
| 9 | `refactor(error): rename CompilationError → Compile` | `cedrus/error.py`, all import sites | `Compile` subclass of `Policy` |
| 10 | `refactor(error): rename ValidationError → Validate` | `cedrus/error.py`, all import sites | `Validate` subclass of `Policy` |
| 11 | `refactor(error): rename GeneratorError → Generate` | `cedrus/error.py`, all import sites | `Generate` subclass of `Policy` |
| 12 | `refactor(error): rename ScopeError → Scope` | `cedrus/error.py`, all import sites | `Scope` subclass of `Policy` |
| 13 | `refactor(error): rename StorageError → Store` | `cedrus/error.py`, all import sites | `Store` subclass of `Error` |
| 14 | `refactor(error): rename WorkspaceError → Space` | `cedrus/error.py`, all import sites | `Space` subclass of `Error` |
| 15 | `refactor(error): rename DeploymentError → Deploy` | `cedrus/error.py`, all import sites | `Deploy` subclass of `Error` |

### Verify hierarchy (2 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 16 | `refactor(error): rename VerificationParseError → Parse` | `cedrus/verify.py`, `__init__.py` | `Parse` subclass of `Error` |

### Compiler / Intent (2 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 17 | `refactor(compile): rename PolicyIntent → Intent` | `cedrus/compile.py`, `__init__.py`, all import sites | `Intent` class; all callers updated |
| 18 | `refactor(compile): rename CompiledSource → Source` | `cedrus/compile.py`, `__init__.py`, all import sites | `Source` class |

### Need / Case (5 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 19 | `refactor(need): rename Requirement → Need` | `cedrus/need.py`, `__init__.py`, all import sites | `Need` class |
| 20 | `refactor(case): rename Scenario → Case` | `cedrus/case.py`, `__init__.py`, all import sites | `Case` class |
| 21 | `refactor(case): rename ScenarioResult → Outcome` | `cedrus/case.py`, `__init__.py`, all import sites | `Outcome` class |
| 22 | `refactor(case): rename TestReport → Suite` | `cedrus/case.py`, `__init__.py`, all import sites | `Suite` class |
| 23 | `refactor(validate): rename ValidationReport → Vreport` | `cedrus/validate.py`, `__init__.py`, all import sites | `Vreport` class |

### Scope classes (4 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 24 | `refactor(scope): rename PrincipalScope → Principal` | `cedrus/scope.py`, `__init__.py`, all import sites | `Principal` class |
| 25 | `refactor(scope): rename ActionScope → Action` | `cedrus/scope.py`, `__init__.py`, all import sites | `Action` class |
| 26 | `refactor(scope): rename ResourceScope → Resource` | `cedrus/scope.py`, `__init__.py`, all import sites | `Resource` class |
| 27 | `refactor(scope): rename ConditionClause → Clause` | `cedrus/scope.py`, `__init__.py`, all import sites | `Clause` class |

### Verify classes (3 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 28 | `refactor(verify): rename CedarScopeExtraction → Extraction` | `cedrus/verify.py`, `__init__.py`, all import sites | `Extraction` class |
| 29 | `refactor(verify): rename VerificationFinding → Finding` | `cedrus/verify.py`, `__init__.py`, all import sites | `Finding` class |
| 30 | `refactor(verify): rename VerificationReport → Report` | `cedrus/verify.py`, `__init__.py`, all import sites | `Report` class |

### Generator classes (5 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 31 | `refactor(generate): rename GenerationContext → Context` | `cedrus/generate/contract.py`, `__init__.py`, all import sites | `Context` class |
| 32 | `refactor(generate): rename DraftProposal → Proposal` | `cedrus/generate/contract.py`, `__init__.py`, all import sites | `Proposal` class |
| 33 | `refactor(generate): rename GenerationResult → Result` | `cedrus/generate/contract.py`, `__init__.py`, all import sites | `Result` class |
| 34 | `refactor(generate): rename LiteLLMGenerator → Llm` | `cedrus/generate/llm.py`, `__init__.py`, all import sites | `Llm` class |
| 35 | `refactor(generate): rename OfflineGenerator → Offline` | `cedrus/generate/offline.py`, `__init__.py`, all import sites | `Offline` class |

### Policy classes (3 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 36 | `refactor(policy): rename CompiledPolicy → Compiled` | `cedrus/policy/compiled.py`, `__init__.py`, all import sites | `Compiled` class |
| 37 | `refactor(policy): rename DraftPolicy → Draft` | `cedrus/policy/draft.py`, `__init__.py`, all import sites | `Draft` class |
| 38 | `refactor(policy): rename ExistingPolicy → Existing` | `cedrus/policy/existing.py`, `__init__.py`, all import sites | `Existing` class |

### Schema (1 commit)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 39 | `refactor(schema): rename CedarSchema → Schema` | `cedrus/schema.py`, `__init__.py`, all import sites | `Schema` class |

### Deploy classes (7 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 40 | `refactor(deploy): rename DeploymentManifest → Manifest` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Manifest` class |
| 41 | `refactor(deploy): rename DeploymentRecord → Record` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Record` class |
| 42 | `refactor(deploy): rename BundleExporter → Bundler` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Bundler` class |
| 43 | `refactor(deploy): rename SSRFGuard → Guard` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Guard` class |
| 44 | `refactor(deploy): rename PinnedAddress → Pin` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Pin` class |
| 45 | `refactor(deploy): rename DeploymentClient → Client` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Client` class |
| 46 | `refactor(deploy): rename _PinnedTransport → Transport` | `cedrus/deploy.py`, `__init__.py`, all import sites | `Transport` class |

### Store classes (5 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 47 | `refactor(store): rename StoredPolicy → Stored` | `cedrus/store/sqlite.py`, `__init__.py`, all import sites | `Stored` class |
| 48 | `refactor(store): rename StoredDraft → DraftStored` | `cedrus/store/sqlite.py`, `__init__.py`, all import sites | `DraftStored` class |
| 49 | `refactor(store): rename StoredReport → ReportStored` | `cedrus/store/sqlite.py`, `__init__.py`, all import sites | `ReportStored` class |
| 50 | `refactor(store): rename InMemoryRepository → Memory` | `cedrus/store/memory.py`, `__init__.py`, all import sites | `Memory` class |
| 51 | `refactor(store): rename SqliteRepository → Sqlite` | `cedrus/store/sqlite.py`, `__init__.py`, all import sites | `Sqlite` class |

### Keep-as-is (3 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 52 | `refactor(generate): keep Generator Protocol name` | `cedrus/generate/contract.py` | `Generator` Protocol preserved (already single-word) |
| 53 | `refactor(policy): keep Policy base abstract name` | `cedrus/policy/base.py` | `Policy` abstract base preserved |
| 54 | `refactor(store): keep Repository Protocol name` | `cedrus/store/contract.py` | `Repository` Protocol preserved at this stage; segregation in Phase D |

---

## Phase C — Filename renames (12 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 55 | `chore(rename): merge scope_json.py into scope.py` | `cedrus/scope_json.py` → `cedrus/scope.py` (merged) | `scope_json.py` removed; `scope.py` contains both classes and codec helpers |
| 56 | `chore(rename): compiler.py → compile.py` | `git mv` | File renamed; all imports updated |
| 57 | `chore(rename): deployment.py → deploy.py` | `git mv` | File renamed; all imports updated |
| 58 | `chore(rename): errors.py → error.py` | `git mv` | File renamed; all imports updated |
| 59 | `chore(rename): migrations.py → migrate.py` | `git mv` | File renamed; all imports updated |
| 60 | `chore(rename): requirements.py → need.py` | `git mv` | File renamed; all imports updated |
| 61 | `chore(rename): scenarios.py → case.py` | `git mv` | File renamed; all imports updated |
| 62 | `chore(rename): validation.py → validate.py` | `git mv` | File renamed; all imports updated |
| 63 | `chore(rename): verification.py → verify.py` | `git mv` | File renamed; all imports updated |
| 64 | `chore(rename): workspace.py → space.py` | `git mv` | File renamed; all imports updated |
| 65 | `chore(rename): generator/ → generate/` | `git mv` | Directory renamed; package init updated |
| 66 | `chore(rename): storage/ → store/` | `git mv` | Directory renamed; package init updated |

---

## Phase D — Repository Protocol segregation (12 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 67 | `feat(store): introduce NeedRepository Protocol` | `cedrus/store/contract.py` | Protocol with `add`, `get`, `list`, `remove` methods |
| 68 | `feat(store): introduce StoredRepository Protocol` | `cedrus/store/contract.py` | Protocol with `upsert`, `get`, `list`, `remove` methods |
| 69 | `feat(store): introduce DraftRepository Protocol` | `cedrus/store/contract.py` | Protocol with `append`, `update`, `latest`, `list` methods |
| 70 | `feat(store): introduce ReportRepository Protocol` | `cedrus/store/contract.py` | Protocol with `log`, `latest` methods |
| 71 | `feat(store): introduce DeployRepository Protocol` | `cedrus/store/contract.py` | Protocol with `record`, `list` methods |
| 72 | `feat(store): introduce UnitOfWork Protocol` | `cedrus/store/contract.py` | Protocol with `transaction` method |
| 73 | `refactor(store): implement Sqlite as union of all 6 Protocols` | `cedrus/store/sqlite.py` | `Sqlite` declares all 6 Protocol bases |
| 74 | `refactor(store): implement Memory as union of all 6 Protocols` | `cedrus/store/memory.py` | `Memory` declares all 6 Protocol bases |
| 75 | `refactor(store): apply @overload on Sqlite.add for type dispatch` | `cedrus/store/sqlite.py` | `add` overloaded for `Need`, `Stored`, `DraftStored`, `ReportStored`, `Record` |
| 76 | `refactor(store): apply @overload on Sqlite.upsert for type dispatch` | `cedrus/store/sqlite.py` | `upsert` overloaded for `Stored`, `DraftStored` |
| 77 | `refactor(store): drop the monolithic Repository Protocol in favor of 6 segregated Protocols` | `cedrus/store/contract.py` | Only 6 Protocols exported |
| 78 | `refactor(space): Space takes a single repo argument typed as Protocol union` | `cedrus/space.py` | `Space.__init__` accepts `Sqlite \| Memory` |

---

## Phase E — Wire-shape classes (15 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 79 | `feat(data): introduce Headers class with to_dict, from_strings, validate` | `cedrus/data/wire.py` | `Headers(items: tuple[tuple[str, str], ...])` |
| 80 | `feat(data): introduce Body class with sha256 auto-compute` | `cedrus/data/wire.py` | `Body(payload: bytes, content_type: str)` |
| 81 | `feat(data): introduce Receipt class with to_dict, from_dict` | `cedrus/data/wire.py` | `Receipt(status_code, body_sha256, idempotency_key, retry_count)` |
| 82 | `feat(data): introduce Target class with local/remote factory classmethods` | `cedrus/data/wire.py` | `Target.local(path)`, `Target.remote(url)` |
| 83 | `feat(data): introduce Usage class with prompt/completion/total` | `cedrus/data/wire.py` | `Usage(prompt, completion, total)` |
| 84 | `feat(data): introduce Notes class with to_dict, from_dict` | `cedrus/data/wire.py` | `Notes(items: tuple[tuple[str, str], ...])` |
| 85 | `feat(data): introduce Metadata class with to_dict, from_dict` | `cedrus/data/wire.py` | `Metadata(items: tuple[tuple[str, str], ...])` |
| 86 | `feat(data): introduce Unresolved class with add, merge, __len__` | `cedrus/data/wire.py` | `Unresolved(items: tuple[str, ...])` |
| 87 | `feat(data): introduce Payload class with to_dict, from_dict` | `cedrus/data/wire.py` | `Payload(data: dict[str, object])` |
| 88 | `feat(data): introduce Message class wrapping a Cedar-formatted string` | `cedrus/data/wire.py` | `Message(text: str)` |
| 89 | `feat(data): introduce Context class carrying Need + Domain + scopes` | `cedrus/data/transit.py` | `Context(need, domain, principal, action, resource, existing)` |
| 90 | `feat(data): introduce Proposal, Result classes for generator output` | `cedrus/data/transit.py` | `Proposal`, `Result` classes |
| 91 | `feat(data): introduce Request, Response classes for HTTP envelopes` | `cedrus/data/transit.py` | `Request`, `Response` classes |
| 92 | `feat(data): introduce Status, Kind, Value helper classes (for runtime invariants)` | `cedrus/data/wire.py` | Helper classes |
| 93 | `feat(data): add data/__init__.py with re-exports of every wire-shape class` | `cedrus/data/__init__.py` | `__all__` exports all wire-shape classes |

---

## Phase F — Abstract bases + enums (12 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 94 | `feat(scope): introduce Scope abstract base class` | `cedrus/scope.py` | `Scope(ABC)` with `clause()` and `to_dict()` abstract |
| 95 | `feat(scope): make Principal inherit from Scope` | `cedrus/scope.py` | `class Principal(Scope)` |
| 96 | `feat(scope): make Action inherit from Scope` | `cedrus/scope.py` | `class Action(Scope)` |
| 97 | `feat(scope): make Resource inherit from Scope` | `cedrus/scope.py` | `class Resource(Scope)` |
| 98 | `feat(scope): make Clause inherit from Scope` | `cedrus/scope.py` | `class Clause(Scope)` |
| 99 | `feat(policy): introduce Policy abstract base class` | `cedrus/policy/base.py` | `Policy(ABC)` with `id`, `cedar`, `need_id`, `to_intent`, `compile`, `to_dict` |
| 100 | `feat(policy): make Compiled inherit from Policy` | `cedrus/policy/compiled.py` | `class Compiled(Policy)` |
| 101 | `feat(policy): make Draft inherit from Policy` | `cedrus/policy/draft.py` | `class Draft(Policy)` |
| 102 | `feat(policy): make Existing inherit from Policy` | `cedrus/policy/existing.py` | `class Existing(Policy)` |
| 103 | `feat(error): introduce Error abstract base` | `cedrus/error.py` | `class Error(Exception, ABC)` |
| 104 | `feat(error): make every concrete error inherit from Error` | `cedrus/error.py` | All error subclasses inherit from `Error` |
| 105 | `feat(enum): introduce top-level Effect, Decision, Severity, TargetKind, ReportKind enums` | `cedrus/error.py` or new module | `Effect`, `Decision`, `Severity`, `TargetKind`, `ReportKind` StrEnums |

---

## Phase G — Scope discriminator constants (5 commits)

| # | Commit | Files | Acceptance |
|---|--------|-------|------------|
| 106 | `feat(scope): Principal class-level discriminator constants (ANY, SPECIFIC, TYPE, IN_GROUP, IS_TYPE)` | `cedrus/scope.py` | `Principal.ANY = "any"` etc. |
| 107 | `feat(scope): Action class-level discriminator constants (ANY, NAMED, IN_GROUP)` | `cedrus/scope.py` | `Action.ANY = "any"` etc. |
| 108 | `feat(scope): Resource class-level discriminator constants (ANY, SPECIFIC, TYPE, IN_PARENT, IS_TYPE)` | `cedrus/scope.py` | `Resource.ANY = "any"` etc. |
| 109 | `feat(scope): Principal.kind validated against class-level set in __post_init__` | `cedrus/scope.py` | `__post_init__` raises `Scope` if kind invalid |
| 110 | `feat(scope): Action.kind and Resource.kind validated in __post_init__` | `cedrus/scope.py` | Both `__post_init__` validate kinds |

---

## Phase H — Data class methods (~70 commits)

Each commit introduces one method on one data class.

### Scope methods (12 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 111 | `refactor(scope): Principal.to_dict` | `Principal.to_dict()` returns dict |
| 112 | `refactor(scope): Principal.from_dict classmethod` | `Principal.from_dict(data)` reconstructs |
| 113 | `refactor(scope): Principal.clause` | `Principal.clause()` returns Cedar fragment |
| 114 | `refactor(scope): Action.to_dict` | |
| 115 | `refactor(scope): Action.from_dict` | |
| 116 | `refactor(scope): Action.clause` | |
| 117 | `refactor(scope): Resource.to_dict` | |
| 118 | `refactor(scope): Resource.from_dict` | |
| 119 | `refactor(scope): Resource.clause` | |
| 120 | `refactor(scope): Clause.to_dict` | |
| 121 | `refactor(scope): Clause.from_dict` | |
| 122 | `refactor(scope): Clause.clause` | |

### Compile methods (5 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 123 | `refactor(compile): Intent.to_dict` | |
| 124 | `refactor(compile): Intent.from_dict` | |
| 125 | `refactor(compile): Intent.compile` | `intent.compile() → Source` |
| 126 | `refactor(compile): Source.to_dict` | |
| 127 | `refactor(compile): drop old free-function render_principal / render_action / render_resource` | All render_* free functions removed; replaced by `Scope.clause()` |

### Deploy methods (4 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 128 | `refactor(deploy): Manifest.to_dict` | |
| 129 | `refactor(deploy): Manifest.payload` | `payload()` replaces `to_manifest_payload()` |
| 130 | `refactor(deploy): Manifest.from_dict` | |
| 131 | `refactor(deploy): drop old free-function `BundleExporter` style usages` | Old API removed |

### Need methods (4 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 132 | `refactor(need): Need.from_row` | `Need.from_row(row)` |
| 133 | `refactor(need): Need.render` | `need.render()` replaces `render_requirement()` |
| 134 | `refactor(need): Need.load classmethod` | `Need.load(path)` replaces `load_requirement()` |
| 135 | `refactor(need): Need.load_all classmethod` | `Need.load_all(dir)` replaces `load_requirements()` |

### Case methods (5 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 136 | `refactor(case): Case.from_dict` | |
| 137 | `refactor(case): Case.to_dict` | |
| 138 | `refactor(case): Outcome.from_dict` | |
| 139 | `refactor(case): Outcome.to_dict` | |
| 140 | `refactor(case): Suite.from_outcomes` | `Suite.from_outcomes(outcomes)` classmethod |

### Verify methods (5 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 141 | `refactor(verify): Finding.to_dict` | |
| 142 | `refactor(verify): Report.to_dict` | |
| 143 | `refactor(verify): Vreport.to_dict` | |
| 144 | `refactor(verify): Extraction.to_dict` | |
| 145 | `refactor(verify): Extraction.matches` | `e1.matches(e2)` polymorphic shadow check |

### Generate methods (5 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 146 | `refactor(generate): Context.from_need_and_domain` | |
| 147 | `refactor(generate): Proposal.from_intent` | |
| 148 | `refactor(generate): Result.from_proposal` | |
| 149 | `refactor(generate): Proposal uses Unresolved instead of tuple[str, ...]` | |
| 150 | `refactor(generate): Result uses Usage instead of dict[str, int]` | |

### Store methods (~10 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 151 | `refactor(store): Stored.from_row` | |
| 152 | `refactor(store): Stored.to_dict` | |
| 153 | `refactor(store): DraftStored.from_row` | |
| 154 | `refactor(store): DraftStored.to_dict` | |
| 155 | `refactor(store): ReportStored.from_row` | |
| 156 | `refactor(store): ReportStored.to_dict` | |
| 157 | `refactor(store): Record.from_row` | |
| 158 | `refactor(store): Record.to_dict` | |
| 159 | `refactor(store): Record uses Receipt instead of Mapping[str, str] response` | |
| 160 | `refactor(store): DraftStored uses Notes, Unresolved instead of dict/tuple` | |

### Manifest metadata + Intent notes (5 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 161 | `refactor(compile): Intent.notes uses Notes instead of Mapping[str, str]` | |
| 162 | `refactor(deploy): Manifest.metadata uses Metadata instead of Mapping[str, str]` | |
| 163 | `refactor(generate): Context carries Domain (not separate schema)` | |
| 164 | `refactor(deploy): wire every wire-shape class into a coherent __all__` | |
| 165 | `refactor(compile): Source.to_dict` | |
| 166 | `refactor(verify): drop old free-function aliases` | |
| 167 | `refactor(validate): drop old free-function aliases` | |
| 168 | `refactor(migrate): drop old free-function aliases` | |
| 169 | `refactor(scope): drop old free-function aliases` | |
| 170 | `refactor(need): drop old free-function aliases` | |
| 171 | `refactor(case): drop old free-function aliases` | |
| 172 | `refactor(deploy): drop old free-function aliases` | |
| 173 | `refactor(generate): drop old free-function aliases` | |
| 174 | `refactor(store): drop old free-function aliases` | |

---

## Phase I — Orchestrator class methods (~30 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 175 | `refactor(verify): introduce Verifier class skeleton` | `Verifier(schema)` constructor |
| 176 | `refactor(verify): move verify onto Verifier.verify` | `verifier.verify(policies)` |
| 177 | `refactor(verify): move extract onto Parser.extract` | `parser.extract(policy)` |
| 178 | `refactor(verify): move shadow onto Verifier.shadow` | |
| 179 | `refactor(verify): move redundant onto Verifier.redundant` | |
| 180 | `refactor(verify): move coverage_action onto Verifier.coverage_action` | |
| 181 | `refactor(verify): move coverage_need onto Verifier.coverage_need` | |
| 182 | `refactor(verify): move types onto Verifier.types` | |
| 183 | `refactor(verify): move uncovered onto Verifier.uncovered` | |
| 184 | `refactor(verify): drop old free-function aliases` | |
| 185 | `refactor(validate): introduce Validator class with validate(cedars) and validate_policy(policy)` | Polymorphic on `Policy` |
| 186 | `refactor(validate): drop validate_cedar free function` | |
| 187 | `refactor(compile): introduce Compiler class with compile(intent)` | |
| 188 | `refactor(compile): drop compile_intent free function` | |
| 189 | `refactor(migrate): introduce Migrator class with detect() and migrate()` | |
| 190 | `refactor(migrate): drop legacy_* free functions` | |
| 191 | `refactor(case): introduce Runner class with run(cases) and load(domain)` | |
| 192 | `refactor(case): drop run_scenarios and load_scenarios free functions` | |
| 193 | `refactor(bundler): introduce Bundler class with bundle(domain), write(manifest, dir), read(dir)` | |
| 194 | `refactor(bundler): drop free-function helper usages` | |
| 195 | `refactor(client): introduce Client class with deploy(manifest, target), deploy_local, deploy_remote` | |
| 196 | `refactor(guard): introduce Guard class with check(url) → Pin` | |
| 197 | `refactor(transport): Transport class with handle_request(request)` | |
| 198 | `refactor(deploy): drop free-function helper style in deploy module` | |
| 199 | `refactor(generate): align Offline and Llm to Generator protocol` | |
| 200 | `refactor(need): wrap loaders into Need classmethods (load, load_all)` | Already in Phase H; consolidated here |
| 201 | `refactor(cli): introduce Cli class with ArgParser inner` | |
| 202 | `refactor(cli): move main() onto Cli.run()` | |
| 203 | `refactor(cli): move command_* handlers onto Cli` | |
| 204 | `refactor(deploy): Headers.from_strings replaces parse_headers` | |

---

## Phase J — Domain + Space redesign (~30 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 205 | `feat(domain): introduce Domain dataclass skeleton` | `Domain(name, root, schema, needs, cases, policies, drafts, manifests, bundles, reports)` |
| 206 | `feat(domain): add Domain.mutate method` | `domain.mutate(**changes)` |
| 207 | `feat(domain): add Domain.to_dict method` | |
| 208 | `feat(domain): add Domain.create classmethod` | `Domain.create(name, root)` |
| 209 | `feat(domain): add Domain.load classmethod (accepts Schema)` | `Domain.load(schema, *, root, name)` |
| 210 | `feat(domain): add Domain.refresh method` | |
| 211 | `feat(domain): add Domain.__eq__ and Domain.__hash__` | |
| 212 | `feat(context): Context carries Domain (not separate schema)` | Already covered in H; consolidate |
| 213 | `feat(draft): Draft classmethod Draft.from_need` | |
| 214 | `feat(draft): Draft.compile() → Source` | |
| 215 | `feat(draft): Draft.validate(schema) → Vreport` | |
| 216 | `feat(draft): Draft.add → single-word method` | `draft.add(item: UnresolvedItem)` |
| 217 | `refactor(space): rename Workspace → Space` | Class rename |
| 218 | `refactor(space): Space.create classmethod` | |
| 219 | `refactor(space): Space.open classmethod (with allow_legacy)` | |
| 220 | `refactor(space): Space.init(name) → Domain` | |
| 221 | `refactor(space): Space.load(schema, *, name) → Domain` | |
| 222 | `refactor(space): Space.create(draft) → DraftStored` | |
| 223 | `refactor(space): Space.generate(context) → Draft` | |
| 224 | `refactor(space): Space.apply(draft \| need) → Compiled (polymorphic)` | |
| 225 | `refactor(space): Space.existing_policies(domain) → list[Existing]` | |
| 226 | `refactor(space): Space.policies(domain) → list[Compiled]` | |
| 227 | `refactor(space): Space.export(domain) → Domain (mutates domain.manifests)` | |
| 228 | `refactor(space): Space.write(bundle) → Path` | |
| 229 | `refactor(space): Space.deploy(domain, target, ...) → Record` | |
| 230 | `refactor(space): Space.bundle_build(domain) → Manifest` | |
| 231 | `refactor(space): Space.bundle_write(bundle) → Path` | |
| 232 | `refactor(space): drop the old Workspace method aliases` | |
| 233 | `refactor(space): Space holds single repo typed as Protocol union` | |

---

## Phase K — Method renames in Domain flow (~10 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 234 | `refactor(space): drop require_file_load in favor of Space.create(need)` | |
| 235 | `refactor(space): drop require_dir_load in favor of Space.create(need) for each` | |
| 236 | `refactor(space): drop need_load in favor of Need.load classmethod` | |
| 237 | `refactor(space): drop need_load_all in favor of Need.load_all classmethod` | |
| 238 | `refactor(space): drop draft_create in favor of Space.create(draft)` | |
| 239 | `refactor(space): drop draft_generate in favor of Space.generate(context)` | |
| 240 | `refactor(space): drop compiled_apply in favor of Space.apply(draft)` | |
| 241 | `refactor(space): drop draft_apply in favor of Space.apply(need)` | |
| 242 | `refactor(space): drop compiled_upsert in favor of Space.apply persistence side effect` | |
| 243 | `refactor(space): drop domain_verify in favor of Verifier.verify` | |

---

## Phase L — Final cleanup (~10 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 244 | `refactor(verify): drop the leading-underscore symbols` | `_parse_with_ast` → `parse_ast`, etc. |
| 245 | `refactor(migrate): drop the leading-underscore symbols` | `_RepoLike` → `RepoLike`, `_migrate_policy` → `policy_migrate`, etc. |
| 246 | `refactor(deploy): drop the leading-underscore symbols` | `_PinnedTransport` (already Transport), `_round_trip_http` → `round_trip`, etc. |
| 247 | `refactor(scope): drop the leading-underscore symbols` | `_qualify` → `qualify` |
| 248 | `refactor(space): rename remaining multi-word variables` | `requirement_id` → `need_id`, `requirements_directory` → `needs_dir`, etc. |
| 249 | `refactor(deploy): rename remaining multi-word variables` | `response_data` → `receipt`, etc. |
| 250 | `refactor(verify): rename remaining multi-word variables` | `principal_signature` → `principal_tuple`, etc. |
| 251 | `refactor(cli): rename remaining multi-word variables` | `template_dir` → `dir`, `policy_text` → `text`, etc. |
| 252 | `refactor: enforce single-word methods via custom ruff check (no _need, _policy, etc. suffixes)` | CI lint rule |
| 253 | `refactor: enforce mutation only via Domain.mutate via custom ruff check` | CI lint rule |

---

## Phase M — Tests + docs + CI (~12 commits)

| # | Commit | Acceptance |
|---|--------|------------|
| 254 | `chore(rename): update test imports and class references` | All test files reference `cedrus.*` |
| 255 | `chore(rename): update example/api_examples.py to cedrus namespace` | |
| 256 | `chore(rename): update .github/workflows to cedrus binary name` | `cedrus` binary replaces `cedar-intent` |
| 257 | `chore(rename): update docs/*.md to use new class and module names` | README, architecture.md, cli.md, python-api.md, deployment.md, verification.md |
| 258 | `chore(rename): update issue and PR templates to cedrus branding` | .github/ISSUE_TEMPLATE/*.md, PULL_REQUEST_TEMPLATE.md |
| 259 | `chore(rename): update CHANGELOG.md with the rename` | New `[0.7.0]` section populated |
| 260 | `chore(ci): rename coverage gate artifact and codecov target` | |
| 261 | `docs: add a Glossary mapping old → new names with polymorphism notes` | docs/glossary.md |
| 262 | `test: add tests for new single-word methods (Principal.IS_TYPE, Effect.PERMIT, etc.)` | |
| 263 | `test: add tests for polymorphic Space.apply (Draft and Need overloads)` | |
| 264 | `test: add tests for new Domain.mutate contract and Repository Protocol segregation` | |
| 265 | `chore(release): tag v0.7.0 (final commit on branch)` | |

---

## Acceptance gates

After every commit:

- `pytest tests/` must pass (existing 299 tests + new ones as added)
- `ruff check .` must be clean
- `mypy --strict` must be clean
- No `cedar_intent` strings in `.py` files (after Phase A)
- No `_x` leading-underscore symbols (after Phase L)
- Every public method is single-word verb (after Phase K)

After every phase:

- `pytest --cov=cedrus --cov-fail-under=88` must pass
- All new commits follow the standard commit-message format
- `git grep -n "_[a-z]"` returns zero hits (after Phase L)

After Phase M (final):

- 265 commits total (1–265 enumerated above; the plan targets this exact number)
- All 7 docs files updated
- CHANGELOG `[0.7.0]` section complete
- All tests pass; coverage ≥ 88%
- ruff clean; mypy --strict clean
- `python -c "import cedrus"` works
- `cedrus --help` works
