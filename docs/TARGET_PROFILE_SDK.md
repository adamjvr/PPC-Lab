# Target Profile SDK

PPC Lab v3.1 formalizes project adapters as **target profiles**. A target profile contains derived metadata, scripts, validation records, and declarations describing external input files. It does not make proprietary target binaries part of PPC Lab.

## Create a profile

```bash
ppc-lab-target init profiles/my-target --id my-target --name "My Target"
```

The generated layout is:

```text
my-target/
├── profile.json
├── README.md
├── scripts/run.sh
├── reference/
└── validation/
```

`profile.json` uses `ppc-lab-target-profile-v1`. The v1 profile API targets PPC32 big-endian PPC Lab workloads and records a minimum PPC Lab semantic version, external inputs, optional entry-point metadata, runtime bindings, and redistribution policy.

## External inputs

Inputs are declared by logical id and environment variable. The default skeleton uses:

```json
{
  "id": "image",
  "env": "PPC_LAB_TARGET",
  "required": true,
  "redistributable": false,
  "sha256": null
}
```

Private/commercial binaries remain outside the profile. Record a SHA-256 when a project needs an exact binary revision.

## Validation

```bash
ppc-lab-target validate profiles/my-target
ppc-lab-target inspect profiles/my-target --json
```

Validation checks the stable schema contract, ids, semantic-version floor, architecture declaration, input declarations, safe relative layout paths, required profile paths, and common binary-container leakage. Binary-like files are rejected from a public profile unless explicitly listed in `redistributable_files`. That list is an explicit policy assertion; it does not grant redistribution rights.

## Reproducible profile packages

```bash
SOURCE_DATE_EPOCH=946684800 \
  ppc-lab-target pack profiles/my-target --out my-target-profile.zip
```

The package is sorted, timestamp-normalized, mode-normalized, and includes `PROFILE-PACKAGE.json` with SHA-256 hashes of every included file. Repeating the command with the same profile bytes and `SOURCE_DATE_EPOCH` produces the same ZIP bytes.

## Compatibility policy

- `profile_api = 1` is stable throughout PPC Lab 3.x unless a real target proves it insufficient.
- New optional fields may be added without changing the profile API.
- Existing required field meaning is not changed within profile API v1.
- PPC Lab project/version compatibility is expressed separately by `minimum_ppc_lab`.
- Target-specific addresses, hashes, scripts, and runtime policy stay in the profile; reusable binary-format/runtime mechanics belong in generic PPC Lab only after repeated need is demonstrated.

## Licensing boundary

SDK-generated scripts and metadata intended for this repository are GPL-3.0-only. External target binaries keep their original legal status and are never relicensed merely by being analyzed with PPC Lab.
