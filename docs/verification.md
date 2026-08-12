# Verification semantics

`cedar-intent` ships a static verification pass that runs on the
compiled policy set for a domain. The checks are conservative
approximations of the formal properties the upstream Cedar symbolic
compiler would prove. This page documents exactly what each check
detects and what its false-positive / false-negative characteristics
are.

## Reports

A verification run produces a `VerificationReport`:

```python
{
    "domain": "hr",
    "passed": True,
    "findings": [...],
    "requirements_covered": ["HR-001", "HR-042"],
    "requirements_uncovered": [],
    "actions_covered": ["viewPhoto"],
    "actions_uncovered": [],
}
```

`report.passed` is `True` when no warning-level findings exist. `info`
findings (if any are added in the future) do not affect `passed`.

## Checks

### Shadowing

A `forbid` policy shadows a `permit` policy when the `forbid`'s scope
dominates the `permit`'s scope. The check is conservative: it only
detects exact scope-signature matches between a `forbid` and a
`permit`. A `forbid` that is a strict superset will not be flagged by
this rule; use the Cedar symbolic compiler if you need full
subsumption analysis.

Example:

```cedar
permit (principal == User::"alice", action == Action::"view", resource == Photo::"p1");
forbid (principal == User::"alice", action == Action::"view", resource);
```

The second policy shadows the first; verification reports a
`shadowing` warning.

### Redundancy

Two policies are redundant when they share the same effect and the
same scope signature across all three slots (principal, action,
resource). The check detects strict duplication; it does not detect
partial subsumption (for example, a `permit(any User, ...)` and a
`permit(User::"alice", ...)` are not redundant even though the second
is implied by the first).

Example:

```cedar
permit (principal, action, resource);
permit (principal, action, resource);
```

Verification reports a `redundancy` warning for the second policy.

### Action coverage

Every action declared in the schema should be referenced by at least
one policy. The check is name-based: an action is covered when a
policy references the action name (or group) explicitly. Policies
using `action == any` do not cover any specific action.

A missing action suggests either a forgotten requirement or an
unmodeled schema entry. Resolve it by either adding a policy that
references the action or by removing the action from the schema.

### Requirement coverage

Every loaded requirement should have at least one compiled policy
that references it. The check is by identifier: the requirement's
`id` field must appear as a policy's `requirement_id`.

A missing requirement suggests a requirement file that has not yet
been drafted.

### Entity-type coverage

Every entity type declared in the schema should appear as a
`type_name`, `group_type`, or `parent_type` in at least one policy.
The check is name-based and catches both fully qualified and
unqualified names.

A missing entity type suggests a schema that is over-specified for
the current policy set.

## Recommendations

- Run `cedar-intent verify --strict` in CI to fail builds on warnings.
- Resolve findings before deploying: warnings indicate either
  real bugs or stale inputs that should be cleaned up.
- Treat the report as a starting point. The static checks cover the
  most common cases; full formal verification is the domain of
  `cedar-policy-symcc` and similar tools.

## Limitations

- Scope-dominance analysis is limited to exact signature matches.
  A forbid that is strictly broader than a permit (for example,
  forbid at `resource is Folder::"*"` while the permit is scoped to
  `resource == Folder::"hr/payroll"`) is **not** detected as
  shadowing. This is a known limitation; an out-of-band review is
  required to catch broader-scope forbids.
- Effect-equivalence across permit and forbid is not analyzed.
- Transitive effects (for example, two permits whose union is
  redundant) are not detected.
- Numeric, attribute-based, and template-linked policies are not
  analyzed for coverage in this release.

## What we don't catch (security touchpoints)

The verifier does not analyze:

- **DNS rebinding or SSRF in deployment.** See
  [`SECURITY.md`](../SECURITY.md) and
  [`docs/deployment.md`](deployment.md).
- **LLM prompt injection.** The generator fences user content in the
  prompt and instructs the model to treat markers as data, but a
  hostile requirement text or schema JSON can still bias the model.
  Review every generated policy in a pull request.
- **Auth on HTTP deploy targets.** The deployment client does not
  authenticate by default; you must supply credentials via
  `--header`.
- **Bundle tampering.** The bundle hash in the manifest provides
  corruption detection, not authenticated integrity. Add a keyed
  signature in the deploy metadata when tamper evidence is required.
- **Action groups declared with cycle or self-reference.** A group
  that contains itself produces a stack overflow at coverage time.

## Malformed policy handling

When cedarpy cannot parse a policy, the verifier emits a
`malformed-policy` finding of severity `warning` rather than falling
back to a permissive default. Older versions of the verifier silently
classified unparseable policies as `permit(any, any, any)`; that
behaviour has been removed because it suppressed coverage failures
and hid shadowing. The `verify --strict` CI gate will fail builds
that contain a malformed policy.
