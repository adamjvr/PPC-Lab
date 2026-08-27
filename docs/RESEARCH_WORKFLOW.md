# PPC Lab research workflow

PPC Lab exists to make PowerPC reverse engineering empirical. The target is not to emulate an entire historical machine unless a real research question requires it.

## The loop

```text
static analysis / decompiler hypothesis
              |
              v
identify one callable routine or state transition
              |
              v
load native ELF/Mach-O/PEF or raw research bytes
              |
              v
PPC Lab deterministic call fixture
              |
       +------+------+
       |             |
       v             v
 normal return     concrete stop
       |             |
       v             v
capture state     add smallest reusable
and compare       opcode/stub/mapping support
       |             |
       +------+------+
              |
              v
update decompiler model / clean-room implementation
```

## 1. Start with a narrow question

Good questions:

- What does this constructor initialize?
- Is this argument an index, pointer, bit field, or floating-point value?
- What object offsets change after this method?
- Which branch is selected by this flag?
- What buffer layout comes out of this routine?
- Does the original implementation clamp, wrap, saturate, or truncate?

Bad first questions:

- Can we emulate the whole operating system?
- Can we implement every PowerPC instruction before testing anything?

PPC Lab is demand-driven infrastructure.

## 2. Preserve static-analysis context

A target profile should record routine addresses, transition vectors, TOC values, symbols, import addresses, and the provenance/version of those facts. This allows execution evidence to be related back to Ghidra/IDA/Binary Ninja or manual disassembly.

## 3. Keep proprietary bytes external

Commit scripts, hashes, addresses, symbols, derived metadata, and validation results when legally redistributable. Do not commit commercial binaries merely because a profile needs them.

Profile scripts should accept external paths through environment variables or arguments.

### Prefer direct native intake when supported

Preserve the original ELF, Mach-O, or PEF container when PPC Lab supports it:

```bash
ppc-lab image-info target.bin
ppc-lab symbols target.bin
ppc-lab disasm --pef target.bin --count 32
ppc-lab call --pef target.bin --image-base 0x11000000
```

Native intake preserves container metadata and lets PPC Lab own the reusable relocation/layout work. Extract raw sections only when the original container is unsupported or the active research question genuinely benefits from a preprocessed image.

## 4. Make memory deterministic

A useful function experiment should explicitly control:

- code/data mapping addresses;
- scratch/heap region;
- stack region;
- return sentinel;
- GPR/FPR inputs;
- relevant memory inputs;
- import behavior;
- instruction limit.

If an experiment depends on leftover host memory or an implicit OS service, it is not yet a good regression fixture.

## 5. Treat stops as evidence

### Unsupported instruction

Record the PC and instruction word. Confirm the instruction from static analysis. Implement the smallest correct reusable semantics and add a synthetic test before retrying the target.

### Import trap

Determine what function was imported. Do not return fake success by default. Add a stub only if its semantics are understood enough for the research path.

### Memory fault

Check relocation and pointers first. A memory fault often reveals an incorrect object layout, TOC, ABI assumption, or unprepared global.

### Instruction limit

Inspect control flow and trace. An unexpectedly long run may indicate a bad return address, unhandled import, loop input, or incorrect instruction semantics.

## 6. Compare behavior, not just return codes

Useful evidence includes:

- final GPR/FPR values;
- object-field mutations;
- output buffers;
- call/branch paths;
- instruction counts;
- exact byte hashes;
- float error statistics;
- repeated runs across input vectors.

A normal return is only the beginning of behavioral validation.

## 7. Separate observation from clean-room implementation

For projects that require clean-room boundaries, keep original-binary execution evidence and native reimplementation source/process appropriately separated according to the project's legal and engineering policy. PPC Lab itself can serve as an oracle and test-vector generator; it does not decide the project's legal process.

## 8. Promote stable experiments to profiles

Once a command is repeatedly useful, create:

```text
profiles/<target>/
├── README.md
├── reference/
├── scripts/
└── validation/
```

A good profile makes the question reproducible months or years later without needing chat history.

## 9. Add generic capability only when reusable

If multiple targets need the same loader, ABI helper, instruction family, import behavior, or result tool, promote it into the generic core/tooling. Otherwise keep target-specific knowledge in the profile.

This is how PPC Lab stays useful for years without becoming its own full-time product.
