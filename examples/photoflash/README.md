# PhotoFlash example workspace

This directory contains a complete `cedar-intent` workspace for the
PhotoFlash scenario: users viewing photos in an album.

## Layout

```text
photoflash/
├── hr/
│   ├── schema.json
│   ├── scenarios.json
│   ├── requirements/
│   │   ├── HR-001.md
│   │   └── HR-042.md
│   └── policies/
│       └── p1.cedar
├── README.md
└── scripts/
    └── run.sh
```

## Run the example

```bash
cd photoflash
cedar-intent init --path .
cedar-intent domain add hr
bash scripts/run.sh
```

## Files

- [`hr/schema.json`](hr/schema.json) — Cedar schema with `User` and
  `Photo` entity types and the `viewPhoto` action.
- [`hr/scenarios.json`](hr/scenarios.json) — example authorization
  scenarios for testing.
- [`hr/requirements/HR-001.md`](hr/requirements/HR-001.md) — example
  requirement: photo owners can view their own photos.
- [`hr/requirements/HR-042.md`](hr/requirements/HR-042.md) — example
  requirement: only the album owner can view private photos.
- [`hr/policies/p1.cedar`](hr/policies/p1.cedar) — pre-existing Cedar
  policy imported at setup.
- [`scripts/run.sh`](scripts/run.sh) — end-to-end workflow that
  generates, applies, verifies, and deploys the policy.
