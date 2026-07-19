# Todo example workspace

A minimal workspace showing how to model a single domain with two
roles and one resource. Useful as a starting template for a new
project.

## Layout

```text
todo/
├── tasks/
│   ├── schema.json
│   ├── requirements/
│   │   ├── TSK-001.md
│   │   └── TSK-002.md
│   └── policies/
│       └── public.cedar
├── README.md
└── run.sh
```

## Files

- [`tasks/schema.json`](tasks/schema.json) — schema with `User` and
  `Task` entity types plus four actions (`viewTask`, `createTask`,
  `completeTask`, `deleteTask`).
- [`tasks/requirements/TSK-001.md`](tasks/requirements/TSK-001.md) —
  users may create tasks for themselves.
- [`tasks/requirements/TSK-002.md`](tasks/requirements/TSK-002.md) —
  only task owners may complete or delete their tasks.
- [`tasks/policies/public.cedar`](tasks/policies/public.cedar) — the
  baseline "anyone can view tasks" policy.
- [`run.sh`](run.sh) — end-to-end workflow script.

## Run the example

```bash
cd todo
cedar-intent init --path .
cedar-intent domain add tasks
bash run.sh
```
