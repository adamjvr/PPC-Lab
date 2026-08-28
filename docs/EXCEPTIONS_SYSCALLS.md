# Traps, system calls, and exception boundaries

PPC Lab is a routine-execution harness, not an operating system. v0.5 therefore
makes important software exception boundaries explicit instead of either
crashing or inventing an OS.

## `sc`

An unbound `sc` instruction returns the structured stop reason `system_call` and
the CLI exits with status 9.

For deterministic experiments, bind a fixed return value:

```bash
ppc-lab call --elf target.elf \
  --syscall-return 4=0 \
  --syscall-return 5=0xffffffff
```

Or supply a fallback:

```bash
ppc-lab call --elf target.elf --default-syscall-return 0
```

The current generic binding convention reads the selector from `r0`, writes the
fixed result to `r3`, then continues at the next instruction. This is a useful
research convention for common PPC32 Unix-style ABIs, not a claim that PowerPC
architecture itself assigns those ABI roles. Runtime personalities should own
OS-specific semantics.

## `tw` and `twi`

When a trap condition is true, builtin execution returns `trap` and the CLI exits
with status 8. The stop preserves PC/instruction state so the condition can be
examined directly.

For a deliberate experiment that wants to skip architectural trap handling:

```bash
ppc-lab call --elf target.elf --ignore-traps
```

This advances past matching `tw`/`twi`. It does not suppress memory faults,
unresolved imports, unsupported instructions, or system calls.

## Backend contract

Builtin and Unicorn backends normalize these boundaries to the same PPC Lab stop
reasons where PPC Lab intercepts them. `tests/test_backend_parity.cpp` exercises
state parity when Unicorn support is available.

Future OS personalities may translate selected syscalls/traps into richer
behavior, but unknown boundaries must remain visible by default.
