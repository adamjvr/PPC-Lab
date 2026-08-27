# Runtime personalities

PPC Lab deliberately separates **binary mechanics** from **runtime policy**. A
loader knows how ELF, Mach-O, or PEF represents an undefined symbol. A runtime
personality decides whether a named import should be modeled and which
behavioral stub should satisfy it.

## Included personalities

- `runtimes/libc-posix-minimal.json` — common memory and libm leaf routines.
- `runtimes/classic-mac-minimal.json` — the same core helpers plus
  `BlockMoveData`/`BlockMove` for CFM research.

These are intentionally small. They are not libc, POSIX, or Mac OS emulators.
Unsupported services remain unresolved and therefore visible.

## Use

```bash
python3 scripts/ppc_runtime_call.py \
  --ppc-lab ./build/release/ppc-lab \
  --runtime runtimes/classic-mac-minimal.json \
  --image Target.pef \
  -- --entry-symbol SomeFunction --backend builtin --snapshot /tmp/run.json
```

The runner inspects imports, allocates deterministic identities inside the PPC
Lab import range, emits matching `--bind` and `--stub` arguments, and executes
the normal `ppc-lab call` path. Use `--dry-run` to inspect the generated call.

## Built-in stub kinds

`pow`, `cos`, `sqrt`, `sin`, `exp`, `fabs`, `floor`, `ceil`, `blockmove`,
`memcpy`, `memmove`, `memset`, and `bzero`.

Math stubs use host math and are behavioral helpers rather than bit-exact
claims about a target C library. Memory stubs operate only on mapped PPC Lab
memory and fail explicitly on invalid ranges.

## Adding a personality

Create a JSON file with schema `ppc-lab-runtime-v1`:

```json
{
  "schema": "ppc-lab-runtime-v1",
  "name": "example-runtime",
  "symbols": {
    "_memcpy": "memcpy",
    "BlockMoveData": "blockmove"
  }
}
```

Do not put project-specific absolute addresses into generic runtime files. If a
service requires target state, callbacks, allocation policy, files, windows,
threads, or OS objects, model it as a target profile first and promote only the
reusable portion later.
