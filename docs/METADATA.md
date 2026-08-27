# Machine-readable intake metadata

`ppc-lab metadata FILE` loads a supported native PPC image and emits
`ppc-lab-metadata-v1` JSON. This is the stable v0.4 bridge between PPC Lab's
loaders and external research tooling.

```bash
./build/release/ppc-lab metadata Target.pef > target.metadata.json
./build/release/ppc-lab metadata object.o --image-base 0x12000000 \
  --bind memcpy=0x30000000 > object.metadata.json
```

The document contains:

- normalized format name;
- mapped entry point;
- mapped memory regions and permissions;
- normalized symbols with address, size, section, binding/type, defined state,
  and import state.

Because `metadata` uses the real loader, rebasing and supplied symbol bindings
match subsequent execution. For an image with unresolved relocations that
cannot be loaded yet, use `ppc-lab symbols FILE` first to inspect undefined
symbols and then provide the required `--bind` arguments.
