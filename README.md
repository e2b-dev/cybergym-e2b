# CyberGym on E2B

`cybergym-e2b` is a thin runtime adapter that runs the upstream CyberGym benchmark in
E2B sandboxes and uses Fireworks for inference. CyberGym stays pinned and unmodified as a
git submodule. The adapter owns only template construction, E2B lifecycle and network
policy, final-answer selection, result export, and cross-runtime fidelity checks.

The runtime creates two sandboxes per agent trial:

- A private executor contains upstream CyberGym, Docker, and one task's vulnerable and
  fixed images. Only CyberGym's token-gated submission port is reachable from the agent.
- An agent contains the requested task files and mini-swe-agent. It can reach only the
  executor and `api.fireworks.ai`; it has no E2B key, Docker socket, fixed source, or patch.

CyberGym's own server performs vulnerable execution, deduplication, timeout mapping, fixed
verification, and raw exit-code persistence. The adapter scores exactly one model-designated
`final.poc` as successful when the vulnerable build crashes and the fixed build does not.

## Setup

Python 3.12+, `uv`, an E2B API key, and a Fireworks API key are required.

```bash
git submodule update --init
uv sync --all-groups
cp .env.example .env
```

Set `E2B_API_KEY` and `FIREWORKS_AI_API_KEY` in `.env`, or pass an existing file with
`--env-file`. Credentials are never copied into templates or committed.
The local Docker comparison alone needs the pinned upstream server dependencies; install
them with `uv sync --extra docker-baseline` before running it.

Validate the pinned upstream checkout, keys, and image sizes:

```bash
uv run cybergym-e2b --env-file .env check
```

Download only the task-facing data and build immutable templates for the representative
small, medium, and large sample:

```bash
uv run cybergym-e2b --env-file .env sync --task arvo:1065 --task oss-fuzz:42535201 --task oss-fuzz:370689421
uv run cybergym-e2b --env-file .env build
```

Run the Fireworks sample with a per-task inference ceiling:

```bash
uv run cybergym-e2b --env-file .env run --cost-limit 0.03 --step-limit 30
```

The default model is Fireworks `gpt-oss-20b`. Override it with `--model`. Every trial emits
one JSON result line and writes its trajectory, selected PoC, server result, and result
envelope under `artifacts/`.

## Correctness comparison

Run the same reference PoC on local Docker and E2B, then compare crash classes:

```bash
uv run --extra docker-baseline cybergym-e2b docker-baseline --task arvo:1065 --output artifacts/docker-arvo-1065.json
uv run cybergym-e2b --env-file .env e2b-baseline --task arvo:1065 --output artifacts/e2b-arvo-1065.json
uv run cybergym-e2b compare artifacts/docker-arvo-1065.json artifacts/e2b-arvo-1065.json
```

Byte-identical logs are not required. Correctness requires matching vulnerable/fixed crash
classes and the same final-submission score.

The CI workflow repeats the small reference comparison on native x86_64 Docker. On Apple
Silicon, Docker Desktop emulates these amd64 sanitizer images; sanitizer allocator failures
can make fixed images appear to crash before the target executes, so that result is retained
as portability evidence rather than accepted as the benchmark oracle.

## Capacity and cleanup

`--max-sandbox-concurrency` is hard-capped at 180. Each agent trial reserves two slots, so
at most 90 trials can be active at once. `--workers` may lower that limit. Creates are not
retried blindly because E2B sandbox creation is not idempotent.

Every sandbox has timeout-to-pause as its failure-safe lifecycle. Completed runs are killed
by default to minimize compute and snapshot storage. `--retain` pauses them for inspection.
Each result reconciles its unique `trial_id` and reports any sandbox still running.

E2B disk capacity is account-specific. Template builds reject task image pairs above the
configured compressed-size safety threshold. Raise `--max-compressed-image-gib` only after
checking the team's provisioned disk. Custom templates on the tested E2B team receive about
100 GB of disk, but the default 8 GiB threshold keeps validation builds small and cheap; the
extra-large `oss-fuzz:385167047` pair is 28.6 GiB before unpacking.

## Updating CyberGym

All upstream coupling is explicit:

1. Move `vendor/cybergym` to the intended upstream commit.
2. Update the code and dataset commits in `upstream.lock.json`.
3. Run `check` and the unit suite. A changed task-generation submission template fails with
   a compatibility error instead of silently producing an insecure request.
4. Rebuild templates and run `docker-baseline`, `e2b-baseline`, and `compare` on the sample.

The manifest records immutable E2B build IDs and both upstream commits. Runtime refuses a
manifest whose pins do not match `upstream.lock.json`.
