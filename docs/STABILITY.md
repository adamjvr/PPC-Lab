# v1 stability and compatibility contract

PPC Lab 1.0 marks the first stable general-research-platform boundary. Stability here means documented interfaces change deliberately; it does **not** mean every possible PowerPC instruction, ABI, operating system, relocation, or runtime service is already implemented.

## Stable v1 concepts

The following concepts are intended to remain compatible throughout the 1.x series:

- PPC32 big-endian as the reference guest architecture;
- `ExecutionBackend`, deterministic `Memory`/`CpuState`, `CallHarness`, and shared image-symbol concepts;
- `UniversalImageLoader` as the format-neutral native intake boundary;
- explicit target policy through bindings, runtime stubs, profiles, register/memory setup, and deterministic image bases;
- visible stop reasons rather than invented OS/runtime behavior;
- `ppc-lab-result-v1`, `ppc-lab-snapshot-v1`, `ppc-lab-metadata-v1`, `ppc-lab-analysis-v1`, and `ppc-lab-capabilities-v1` schema identifiers;
- installed CMake target `PPCLab::core` and `find_package(PPCLab CONFIG)` package discovery.

## CLI compatibility

Existing documented options should not silently change meaning in 1.x. New options/commands may be added. `call` and `run` are equivalent; `--image` is the preferred auto-detected native-image input, while explicit `--elf`, `--macho`, and `--pef` inputs remain valid.

Scripts should key machine-readable data by the `schema` field and tolerate additional JSON fields. Human-readable diagnostic prose is not a parsing contract.

## C++ API compatibility

PPC Lab is a small research library, not an ABI-stable shared-library distribution. Source compatibility for documented public headers is the 1.x goal. Consumers should rebuild against new versions. Breaking public C++ changes require a major-version decision or a clearly documented migration when unavoidable.

## What is intentionally not promised

- bit-perfect emulation of every PPC implementation;
- complete operating-system or firmware environments;
- compatibility with unknown relocation families;
- stable behavior for undocumented internal functions;
- PPC64 or little-endian PPC in 1.0;
- identical floating-point edge behavior across every host/backend unless covered by an explicit regression.

When a real target exposes a missing capability, add the smallest correct implementation and preserve a regression. That demand-driven rule remains part of the platform contract.

## Server-worker protocol

Starting with v1.1, `ppc-lab-job-v1` and `ppc-lab-worker-response-v1` are compatibility contracts. Fields may be added compatibly, but existing field meanings are not silently repurposed within the v1 major line. A breaking job/response change requires a new schema name rather than changing `*-v1` in place.

The worker transport is intentionally not fixed to HTTP or any network stack. NDJSON framing is stable for stream mode; authentication, encryption, queues, scheduling, and network exposure remain deployment concerns.

## v1.1–v1.3 automation protocol stability

Server automation is versioned independently from CLI spelling. `ppc-lab-job-v1` and `ppc-lab-worker-response-v1` remain the stable single-job boundary. v1.2 adds `ppc-lab-orchestration-v1` and `ppc-lab-orchestration-summary-v1` above that boundary rather than replacing it. v1.3 similarly adds `ppc-lab-fleet-v1`, `ppc-lab-fleet-job-result-v1`, and `ppc-lab-fleet-summary-v1`; fleet placement/staging remains an outer transport concern and does not redefine a job.

Within PPC Lab 1.x, existing required meanings in these `*-v1` contracts will not be silently redefined. Additive optional fields may appear. A future incompatible contract will use a new schema identifier.

The content-cache key algorithm is an implementation detail of the v1.2 orchestrator, but the cache key is always treated as opaque SHA-256 identity. Consumers should compare/cache it as a string rather than reproduce the algorithm independently.

## Fleet compatibility

Within PPC Lab 1.x, the fleet v1 schema names are compatibility contracts under the same additive-field rule as worker/orchestration v1. Host placement strategy, content-store layout, and the exact cache-key algorithm remain implementation details; clients should consume the recorded schemas/cache key instead of reproducing those internals.

A single fleet run intentionally requires one PPC Lab engine version across participating hosts. This is a reproducibility rule, not a promise that mixed-version execution is semantically safe.

## v1.4 evidence-store compatibility

`ppc-lab-evidence-query-v1`, `ppc-lab-evidence-report-v1`, and `ppc-lab-evidence-verify-v1` are machine-readable v1 contracts under the same additive-field rule. The local evidence database has its own integer store-schema version; breaking database changes require an explicit migration path rather than reinterpretation in place.

Content-addressed object identity is SHA-256 of PPC Lab's canonical JSON encoding. Callers may persist the reported object SHA as stable semantic evidence identity, but should treat SQL table/layout details as implementation details. Evidence ingestion does not imply ownership, redistribution permission, or archival of target binaries; v1.4 records input hashes/provenance only.

## v1.5 HTTP API compatibility

`ppc-lab-http-api-v1` is an optional transport over the existing stable worker/evidence contracts. `POST /v1/run` accepts `ppc-lab-job-v1` and returns `ppc-lab-worker-response-v1`; the HTTP layer does not define a competing execution payload. Existing v1.5 endpoint meanings will not be silently repurposed within PPC Lab 1.x, and additive endpoints/fields may appear. A breaking transport contract requires a new protocol identifier.

HTTP status codes describe authentication/request/transport/server state, while deterministic guest execution status remains in the worker response. The built-in HTTP server intentionally does not promise TLS termination, public-internet hardening, multi-user authorization, or a persistent asynchronous job queue; those remain deployment or future demand-driven concerns.


## v1.7 behavioral-corpus compatibility

`ppc-lab-corpus-v1`, `ppc-lab-corpus-case-v1`, and `ppc-lab-corpus-replay-summary-v1` are v1 compatibility contracts. Additive fields are allowed; existing expectation meanings are not silently redefined. Corpus input identity is SHA-256 plus byte size, while `path_hint` is advisory only. Backend names and transport prose are deliberately excluded from the behavioral expectation contract.

Embedding a target input never implies redistribution permission. Public corpora should normally contain only case metadata/hashes plus synthetic or otherwise redistributable embedded objects.

## v1.8 differential-triage compatibility

`ppc-lab-differential-triage-v1` and `ppc-lab-triage-bundle-v1` are additive v1 contracts above the already-stable trace/job/worker formats. Trace execution identity is `(PC, instruction word)`; symbol/disassembly text remains annotation rather than behavioral identity. The report may gain optional fields, but existing classifications and required field meanings will not be silently redefined in 1.x.

A triage bundle is evidence, not a binary archive. Input SHA-256/size provenance is stable research identity, while file paths and engine executable paths are environment-specific metadata. `repro.job.json` is a bounded instruction-budget aid and does not claim byte-level input minimization.

## v1.9 guided-exploration compatibility

`ppc-lab-exploration-v1`, `ppc-lab-exploration-case-v1`, and `ppc-lab-exploration-summary-v1` are additive v1 contracts above `ppc-lab-job-v1`. Existing mutation-path meanings and novelty fields will not be silently repurposed within PPC Lab 1.x. New optional novelty measurements or mutation roots may be added only when they preserve the worker/root safety boundary.

Exploration is deterministic for a given manifest, engine version, target bytes, and backend. The exact internal frontier ordering is an implementation detail; consumers should use the emitted case/summary records rather than reconstructing the scheduler. Target-input identity is SHA-256 plus size, and corpus promotion does not imply permission to redistribute target bytes.
## v2 campaign compatibility

PPC Lab 2.0 adds workflow autonomy without redefining the stable v1 execution schemas. `ppc-lab-job-v1`, worker responses, trace/corpus/triage/evidence contracts, and the target-neutral C++ execution boundaries keep their existing schema identities. v2.0 adds `ppc-lab-campaign-v1`, `ppc-lab-campaign-state-v1`, `ppc-lab-campaign-summary-v1`, and `ppc-lab-campaign-triage-summary-v1` as additive composition contracts.

Campaign resume intentionally pins both the exact manifest SHA-256 and PPC Lab engine version. That strictness is part of the reproducibility contract rather than a compatibility defect: a modified manifest or changed engine must begin a new campaign output directory. Additive optional campaign fields may appear in 2.x; incompatible meanings require a new schema identifier.

The v2 CMake package version is a new major-version boundary for package discovery. The public C++ engine remains source-oriented and target-neutral; consumers should rebuild and request the v2 package explicitly even though v2.0 does not intentionally remove the core v1 intake/execution concepts.

PPC Lab 2.1 extends `ppc-lab-exploration-v1` additively with the deterministic `adaptive` strategy and adds `ppc-lab-priority-policy-v1` / `ppc-lab-priority-report-v1`. Existing guided/cartesian manifests and v2.0 campaign manifests retain their meaning. Campaign intelligence is additive and enabled with documented defaults.


## v2.2 scheduler compatibility

`ppc-lab-scheduler-v1`, `ppc-lab-scheduler-state-v1`, and `ppc-lab-scheduler-summary-v1` are additive 2.x contracts above the existing campaign layer. Project weights/priorities govern deterministic admission only; they do not redefine campaign or guest execution semantics. Terminal scheduler admission states remain terminal on exact resume. Additive optional resource/accounting fields may appear in 2.x; incompatible meanings require a new schema identifier.
