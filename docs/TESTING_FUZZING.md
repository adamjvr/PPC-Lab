# Testing, property checks, and malformed-input stress

PPC Lab is long-lived reverse-engineering infrastructure. Tests are intended to
make it safe to leave the project alone and return months or years later.

## Test layers

`ctest` covers synthetic CPU execution, call setup, ELF/Mach-O/PEF loaders and
relocations, runtime stubs, research scripts, repository invariants, and v0.5
execution hardening.

Important v0.5 suites:

- `ppc_lab_execution_coverage_tests` — focused architectural vectors for traps,
  syscalls, atomics, byte-reversed/update memory forms, overflow/CR logic,
  float-to-int stores, and `dcbz`;
- `ppc_lab_property_tests` — deterministic randomized arithmetic/logical,
  disassembly, and memory-boundary checks;
- `ppc_lab_backend_parity_tests` — builtin-vs-Unicorn final-state comparison
  when Unicorn is compiled in; clean skip otherwise;
- `ppc_lab_malformed_intake` — deterministic malformed ELF/Mach-O/PEF/fat-image
  corpus ensuring inspection rejects bad data without crashes or hangs;
- `ppc_lab_repository_invariants` — GPLv3/SPDX, version synchronization, and
  target-neutral core enforcement.

Randomized tests use fixed seeds. A failing case must therefore be reproducible.

## Sanitizers

On Clang/GCC hosts:

```bash
cmake -S . -B build/sanitize \
  -DCMAKE_BUILD_TYPE=Debug \
  -DPPC_LAB_ENABLE_SANITIZERS=ON
cmake --build build/sanitize --parallel
ctest --test-dir build/sanitize --output-on-failure
```

`./Tools/verify.command` performs the project-standard release/test flow and,
where supported, the sanitizer pass.

## What this is not

The deterministic malformed-input suite is a regression/fuzz-style stress layer,
not a claim of exhaustive security fuzzing. If PPC Lab becomes exposed to
untrusted remote inputs, add a dedicated coverage-guided fuzzing deployment and
threat model rather than relying on these tests alone.
