# cedar-intent roadmap

This file tracks the remaining work for the cedar-intent open-source
release. It is the single source of truth for what is left to do.

## Status snapshot

| Phase | Status | Notes |
|--------|--------|-------|
| Phase 1: Gitignore + CHANGELOG          | done    | `.cedar-intent/` and `.cedar-intent/*` ignored; per-artifact CHANGELOG entries recorded. |
| Phase 2: Verification correctness (M2, M3, M5, M6) | done    | Cedar-source-driven verification, any-does-not-subsume-namespace, condition signatures in redundancy, action-group expansion, namespace-aware action coverage. |
| Phase 3: Deployment correctness (M8-M13) | done    | verify-first deploy gate, atomic local writes, strict `bundle_hash` check, bounded HTTP reads, SSRF guard, `HTTPError` vs `URLError` split. |
| Phase 4: CLI + API contract (M14, M15, m1-m4) | todo    | |
| Phase 5: Comprehensive test additions | todo    | |
| Phase 6: Version 0.6.0 + `cedar-intent migrate` CLI | todo    | |

## Phase 4: CLI + API contract (M14, M15, m1-m4)

Scope: tighten the public CLI and Python surface so cross-domain and
cross-principal mistakes are impossible to make by accident.

| ID | Description | Touched files |
|----|-------------|----------------|
| M14 | Replace single `--entity-id` with `--principal-id` and `--resource-id`. | `cli.py`, `tests/test_cli.py`, `tests/test_verify_deploy_cli.py`, `docs/cli.md` |
| M15 | Reject policy commands whose requirement domain does not match `--domain`. Raise `WorkspaceError` with a one-line fix-it message. | `workspace.py`, `cli.py`, `tests/test_cli.py`, `tests/test_workspace.py` |
| m1 | `Workspace.apply_for_requirement` must raise `WorkspaceError` (not `StorageError`) when no draft exists. Add a regression test that explicitly asserts the exception type. | `workspace.py`, `tests/test_workspace.py` |
| m2 | `BundleExporter.write_directory` and `DeploymentClient.deploy_local` must wrap every filesystem call in `try/except (OSError, ValueError, KeyError, json.JSONDecodeError)` and raise `DeploymentError`. | `deployment.py`, `tests/test_deployment.py` |
| m3 | Reject empty header names, header names/values containing `\r`/`\n`, and `--timeout inf`/`--timeout nan`. | `cli.py`, `tests/test_cli.py` |
| m4 | Reject symlink targets for `BundleExporter.write_directory` and `read_directory`. | `deployment.py`, `tests/test_deployment.py` |

## Phase 5: Comprehensive test suite additions

The existing suite covers happy paths and a few regressions. The
audit identified coverage gaps that should be filled before tagging
0.6.0.

| Group | Tests to add |
|-------|--------------|
| M5 regression: imported policies participate in verification | A new ``CompiledPolicy`` with raw Cedar and ``parsed_intent=None`` must surface action/principal type names in coverage. |
| M6 regression: action group coverage expansion | Cedar `permit (..., action in Action::"readers", ...)` must cover every member of the `readers` group. |
| M6 regression: namespace isolation | Schema with `hr::view` and `finance::view`; a Cedar referencing `hr::view` must not cover `finance::view`. |
| M3 regression: condition signatures matter in redundancy | Two permits with identical scopes but different `when` clauses must not be flagged redundant. |
| M2 regression: `any` does not subsume specifics | `permit (any, ...)` and `forbid (specific, ...)` must not shadow. |
| M11 regression: real HTTP error body is captured | Custom HTTP handler returns 500 + JSON body; error message must contain the body. |
| M12 regression: oversized HTTP body is bounded | Stream 1 MB from a local server; deployment memory must stay bounded. |
| M13 regression: SSRF guard rejects loopback | Default guard rejects `127.0.0.1`. |
| M13 regression: `allow_private_targets=True` permits RFC1918 | RFC1918 target is permitted when flag is set. |
| M9 regression: concurrent writers don't see mixed state | Two threads writing the same directory; final state matches one writer, never a mix. |
| M14 regression: distinct principal/resource ids | CLI invocation with `--principal-id User::alice --resource-id Photo::p1` produces Cedar with both literals. |
| M15 regression: domain mismatch raises `WorkspaceError` | `policy generate HR-042 --domain finance` for an `hr` requirement raises `WorkspaceError`. |
| m1 regression: missing draft raises `WorkspaceError` | `apply_for_requirement("HR-042", ...)` without prior generate raises `WorkspaceError`, not `StorageError`. |
| m2 regression: malformed manifest raises `DeploymentError` | `read_directory` with bad JSON raises `DeploymentError`. |
| m3 regression: empty header name rejected | `parse_headers([": value"])` raises `ConfigError`. |
| m4 regression: symlink target rejected | Writing into a symlinked directory raises `DeploymentError`. |

Target: ~25 new tests covering all of the above.

## Phase 6: Release 0.6.0 and `cedar-intent migrate`

Scope: cut a clean release and surface the migration helper.

| Task | Description |
|------|-------------|
| 6.1 | Add `cedar-intent migrate` subcommand: default reports count of legacy rows; `--apply` performs the migration; `--check` exits non-zero when legacy rows exist (suitable for CI). |
| 6.2 | Add `CHANGELOG.md` `[0.6.0]` section listing the 0.5.0 -> 0.6.0 behavior changes (verified-by-default deploy, atomic writes, SSRF guard, namespace-aware coverage). |
| 6.3 | Bump `cedar_intent.__version__` and `pyproject.toml` version to `0.6.0`. |
| 6.4 | Add `verify_policies` docstring example for action-group coverage. |
| 6.5 | Tag `v0.6.0` and push. |

## Out of scope (deferred to 0.7+)

- Integration with `cedar-policy-symcc` for SMT-backed equivalence
  proofs. The current conservative static checks are sufficient for the
  0.6.0 release.
- Web UI for browsing requirement drafts.
- Auto-deployment from CI to a registry.
- Distributed rate-limited batch deployments.

## Process

- Atomic commits per fix or per test group.
- Each commit message references the audit ID (M1, m2, etc.) when
  applicable so the history is self-documenting.
- Verification gate after every commit:
  ```bash
  .venv/bin/python -m pytest --cov=cedar_intent --cov-fail-under=90
  .venv/bin/python -m ruff check .
  .venv/bin/python -m mypy
  ```
- Tag and push only after Phase 6 passes the gate.
