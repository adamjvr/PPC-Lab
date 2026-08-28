# Behavioral corpus and replay

PPC Lab v1.7 adds a durable behavioral regression layer above the stable `ppc-lab-job-v1` worker contract. The corpus is designed for reverse-engineering work that may be revisited years later: preserve what was executed, exactly which input bytes were used, and which observable machine state was expected.

## Design goals

- **Behavior over labels.** Expectations omit backend names, stdout, temporary paths, and other transport noise. They preserve stop state, instruction count, architectural CPU state, symbols, and memory fingerprints.
- **Exact input identity.** Every code/data input is SHA-256 and size pinned before promotion and verified again before replay.
- **Private binaries stay private.** Promotion records hashes and path hints but does not copy target binaries unless `--embed-input` is explicitly supplied.
- **Contained replay.** Verified inputs are staged into a temporary worker root before execution; replay does not weaken the worker filesystem boundary.
- **Intentional baseline changes are explicit.** `bless` requires `--yes`.
- **Failures become smaller reproductions.** `minimize` removes unnecessary initial register/write/binding setup while preserving the original mismatch path.

## Corpus layout

```text
corpus/
├── manifest.json
├── cases/
│   └── constructor-001.json
└── objects/
    └── sha256/
        └── <hash>       # only when explicitly embedded
```

`manifest.json` uses `ppc-lab-corpus-v1`. Individual cases use `ppc-lab-corpus-case-v1`.

A case stores:

- ID, description, and tags;
- PPC Lab version used when the baseline was created;
- each input field, SHA-256, size, and a non-authoritative path hint;
- a normalized `ppc-lab-job-v1` with `$INPUT:N` placeholders;
- a stable expectation extracted from `ppc-lab-worker-response-v1`.

## Promote a successful experiment

```bash
ppc-lab-corpus promote ./corpus \
  --id distortion-constructor \
  --job ./jobs/distortion.json \
  --description "constructor baseline" \
  --tag classic-mac \
  --tag constructor
```

By default no target bytes enter the corpus. For a synthetic fixture or input you are entitled to redistribute:

```bash
ppc-lab-corpus promote ./corpus \
  --id synthetic-leaf \
  --job ./jobs/leaf.json \
  --embed-input
```

Failed guest executions are not promoted accidentally. Use `--allow-failed-baseline` only when a particular trap/limit/failure state is itself the intended regression.

## Replay private targets

If inputs were not embedded, supply one or more roots containing the target bytes:

```bash
ppc-lab-corpus replay ./corpus \
  --input-root /srv/private-ppc-targets
```

PPC Lab first checks each recorded path hint. If necessary it searches candidate files by recorded size and confirms SHA-256 before staging the match. An exact mapping avoids scans:

```bash
ppc-lab-corpus replay ./corpus \
  --input 012345...cdef=/srv/targets/exact.bin
```

Select cases/tags and override the backend:

```bash
ppc-lab-corpus replay ./corpus \
  --tag mixer \
  --backend unicorn \
  --json /tmp/replay-summary.json
```

The summary schema is `ppc-lab-corpus-replay-summary-v1`. Exit status is zero only when every selected case matches its baseline.

## What is compared

Stable expectation fields include:

- worker success/exit/timeout state;
- stop reason, instruction count, PC/current instruction;
- all compact-result GPRs plus LR/CTR/CR;
- requested dump address/size/FNV-1a64 fingerprints;
- full snapshot CPU state including GPR/FPR bit patterns, LR/CTR/CR/XER/FPSCR;
- mapped region name/base/size/permissions/FNV-1a64 fingerprints;
- loaded symbols;
- snapshot dump fingerprints.

Backend identity, stdout/stderr, temporary filenames, and human-readable messages are deliberately not expectations.

## Verify corpus integrity

```bash
ppc-lab-corpus verify ./corpus
```

Verification checks case schema/IDs, SHA-256 syntax, unique IDs, and the bytes/hash/size of every explicitly embedded object.

## Intentional behavior changes

After reviewing an intentional engine change:

```bash
ppc-lab-corpus bless ./corpus distortion-constructor \
  --input-root /srv/private-ppc-targets \
  --yes
```

`bless` reruns the case and replaces only its behavioral expectation, recording the PPC Lab version that produced the new baseline. It does not change pinned input hashes.

## Minimize a failing case

When a previously passing case starts failing:

```bash
ppc-lab-corpus minimize ./corpus distortion-constructor \
  --input-root /srv/private-ppc-targets \
  --output /tmp/distortion-constructor-minimized.json
```

The current minimizer attempts to remove individual setup entries from GPR/FPR initialization, memory writes, syscall returns, and bindings while preserving at least one original mismatch path. It writes a standalone minimized case and never rewrites the canonical corpus case automatically.

## Source-control policy

Good candidates to commit publicly:

- corpus manifest/case JSON;
- synthetic or freely redistributable embedded fixtures;
- hashes and metadata for proprietary targets.

Do **not** commit proprietary target binaries merely because PPC Lab can embed them. Keep those external and replay by hash from project-controlled storage.
