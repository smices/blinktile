# BlinkTile project instructions

## Model roles and reporting

- Use Astra (`gpt-6-astra`) for planning, analysis, architecture, and independent review.
- Use Sol low (`gpt-5.6-sol`, low) for ordinary bounded tasks.
- Use Luna xhigh (`luna-worker`) for implementation and focused execution.
- If Luna xhigh repeatedly fails to resolve the same bounded task, escalate that worker task to Terra high (`gpt-5.6-terra`, high). Report the fallback.
- Prefix every user-facing progress and final message with the actual model and reasoning level when known, e.g. `【Sol Low】`. Never invent the active model. If the parent runtime does not expose its exact model, say so and identify it as the main agent.
- Do not stop authorized work merely to acknowledge these preferences. Keep independent ownership boundaries and do not overwrite another worker's edits.

## Completion and commits

- After each coherent feature is implemented and its relevant verification passes, create a local Git commit for that feature. This does not authorize pushing.
- Before delivery, review the changes as a reviewer: find bugs, missed edge cases, requirement mismatches, and quality defects.
- Fix confirmed issues at their cause, rerun corresponding checks, and report remaining limitations honestly.
- Distinguish PNG/GIF visual review, protocol simulation, firmware compilation, flashing, and real hardware acceptance.
- Never commit credentials, machine-specific paths, transient build caches, or unrelated work.

## Persistent project memory

Read `docs/project-memory.md` when resuming this project. Record task decisions and verified status there when explicitly requested; do not claim unperformed checks.
