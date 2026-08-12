# Examples

This directory contains example cedrus workspaces and Python API
recipes.

## Workspaces

- [`photoflash/`](photoflash/) — a complete PhotoFlash-style workspace
  with schema, requirements, scenarios, and a generated policy bundle.
- [`todo/`](todo/) — a small Todo-style workspace showing how to model
  a single domain with two roles and one resource.

## API recipes

- [`api_examples.py`](api_examples.py) — runnable Python snippets that
  exercise the public API end to end.

## Try the photoflash workspace

```bash
cd photoflash
cedrus init --path .
cedrus domain add hr
cedrus requirement add hr/requirements/HR-042.md --domain hr
cedrus policy generate HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --offline
cedrus policy apply HR-042 \
    --domain hr \
    --principal specific --principal-type User --entity-id alice \
    --action named --action-name viewPhoto \
    --resource is_type --resource-type Photo \
    --no-scenarios
cedrus --json verify --domain hr
cedrus deploy bundle --domain hr --output ./dist/hr
```

The compiled policy lands in `./dist/hr/bundle.cedar`.
