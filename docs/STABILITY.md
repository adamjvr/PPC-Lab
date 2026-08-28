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
