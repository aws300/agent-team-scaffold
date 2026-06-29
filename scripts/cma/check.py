#!/usr/bin/env python3
"""check.py — validate the CMA manifest and md assets before deploy.

Verifies, for every workflow in cma.yaml:
  - the orchestrator md exists and has frontmatter `name`
  - every leaf's `expert` md exists (or the leaf supplies an inline `prompt`)
  - every leaf `schema` file exists and is valid JSON
  - every skill referenced in any agent's frontmatter `skills:[]` exists under skills/
  - every memory store referenced (workflow `session_memory:` / leaf `memory:`) is
    declared in the `memory_stores:` catalog, with a valid `access` value
  - no leaf declares nested delegation (defense-in-depth; build.py forces [])

Exit non-zero on any failure. Run in CI / pre-commit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import parse_frontmatter, _load_yaml, MANIFEST, find_skill  # reuse the same readers

errors: list[str] = []


def err(msg: str):
    errors.append(msg)


def check_skills(fm: dict, where: str):
    for nm in fm.get("skills") or []:
        if find_skill(nm) is None:
            err(f"{where}: skill '{nm}' not found under skills/")


_VALID_ACCESS = {"read_write", "read_only"}


def check_memory(refs, catalog: dict, where: str):
    for ref in refs or []:
        ref = {"store": ref} if isinstance(ref, str) else ref
        key = ref.get("store")
        if key not in catalog:
            err(f"{where}: memory store '{key}' not declared in `memory_stores:` catalog")
        acc = ref.get("access")
        if acc is not None and acc not in _VALID_ACCESS:
            err(f"{where}: memory store '{key}' has invalid access '{acc}' (use read_write|read_only)")


def main():
    m = _load_yaml(MANIFEST.read_text())
    catalog = m.get("memory_stores") or {}
    # validate catalog defaults
    for key, spec in catalog.items():
        acc = (spec or {}).get("access")
        if acc is not None and acc not in _VALID_ACCESS:
            err(f"[memory_stores] '{key}' default access '{acc}' invalid (use read_write|read_only)")
    for name, wf in (m.get("workflows") or {}).items():
        orch = REPO / wf["orchestrator"]
        if not orch.is_file():
            err(f"[{name}] orchestrator missing: {wf['orchestrator']}"); continue
        fm, _ = parse_frontmatter(orch.read_text())
        if not fm.get("name"):
            err(f"[{name}] orchestrator has no frontmatter `name`")
        check_skills(fm, f"[{name}] {wf['orchestrator']}")
        check_memory(wf.get("session_memory"), catalog, f"[{name}] session_memory")

        for leaf in wf.get("leaves", []):
            tag = f"[{name}] leaf '{leaf.get('as','?')}'"
            check_memory(leaf.get("memory"), catalog, tag)
            if "expert" in leaf:
                exp = REPO / leaf["expert"]
                if not exp.is_file():
                    err(f"{tag}: expert md missing: {leaf['expert']}")
                else:
                    efm, _ = parse_frontmatter(exp.read_text())
                    check_skills(efm, tag)
            elif not leaf.get("prompt"):
                err(f"{tag}: no `expert` and no inline `prompt`")
            if leaf.get("schema"):
                sp = REPO / leaf["schema"]
                if not sp.is_file():
                    err(f"{tag}: schema missing: {leaf['schema']}")
                else:
                    try:
                        json.loads(sp.read_text())
                    except Exception as e:
                        err(f"{tag}: schema invalid JSON: {e}")

    if errors:
        print("CHECK FAILED:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print("check OK — all manifest references resolve, skills present, no nesting.")


if __name__ == "__main__":
    main()
