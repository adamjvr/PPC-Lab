# Orchestration example

`manifest.json` demonstrates the v1.2 orchestration shape. Replace the sample job image paths with target files in your research tree, then run:

```bash
ppc-lab-orchestrate manifest.json --out results --cache .cache --root "$PWD" --parallel 4
```
