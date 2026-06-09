#!/usr/bin/env python3
"""build.py — compile md agent assets into Claude Managed Agents (CMA) JSON.

The CMA layer is ONE python file + ONE tiny manifest (cma.yaml). Instead of
hand-writing a yaml per agent (like financial-services does), this reads the
md assets you already wrote for local Claude Code / Cowork and DERIVES the CMA
deploy payload:

  - system prompt  ← the orchestrator md BODY (frontmatter stripped) + headless_append
  - model          ← cma.yaml `model` (parameterized: ${CMA_MODEL:-sonnet}) or --model
  - tools          ← md frontmatter `tools:` string  → agent_toolset (default-deny + allowlist),
                     further shaped by each leaf's `role` (reader/builder/critic/resolver)
  - skills         ← md frontmatter `skills:[...]`    → resolved to skill dirs under skills/
  - callable_agents← cma.yaml `leaves:` (the orchestration topology — the only thing
                     that can't be inferred from md)
  - output_schema  ← cma.yaml leaf `schema:` (only for reader-role leaves)

Usage:
  python3 scripts/cma/build.py                 # dry-run: print resolved CMA JSON for every workflow
  python3 scripts/cma/build.py combat-feature  # dry-run a single workflow
  python3 scripts/cma/build.py --model opus     # override model
  python3 scripts/cma/build.py --post           # upload skills + POST /v1/agents (needs ANTHROPIC_API_KEY)

No third-party deps for dry-run (pure stdlib + a tiny YAML reader). --post is a stub
showing where the API calls go; wire it to your deploy flow.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # repo root
CMA_DIR = Path(__file__).resolve().parent
MANIFEST = CMA_DIR / "cma.yaml"

# role → which file tools the leaf gets. The whole point of "防任务重叠":
# tools are the task boundary. Only `resolver`/`builder` ever get write.
ROLE_TOOLS = {
    "reader":   ["read", "grep"],                  # untrusted input; NO write, NO mcp
    "critic":   ["read", "grep", "glob"],          # read-only verdict
    "builder":  ["read", "grep", "glob", "write", "edit"],   # writes scoped to src/ by prompt
    "resolver": ["read", "write", "edit"],         # the ONLY writer to ./out/
    "orchestrator": ["read", "grep", "glob"],      # dispatch/aggregate; never writes
}


# ── minimal YAML reader (handles the tiny subset cma.yaml / frontmatter use) ──
def _load_yaml(text: str):
    try:
        import yaml  # use real yaml if available
        return yaml.safe_load(text)
    except Exception:
        pass
    # fallback: cma.yaml is intentionally simple; but prefer pyyaml. Fail loud.
    raise SystemExit("pyyaml required: pip install pyyaml")


def _expand_env(s: str) -> str:
    """Expand ${VAR} and ${VAR:-default} in a string."""
    def repl(m):
        var, default = m.group(1), m.group(3)
        return os.environ.get(var, default if default is not None else m.group(0))
    return re.sub(r"\$\{([A-Z0-9_]+)(:-([^}]*))?\}", repl, s)


def parse_frontmatter(md_text: str):
    """Return (frontmatter_dict, body) from a markdown file."""
    if md_text.startswith("---"):
        end = md_text.find("\n---", 3)
        if end != -1:
            fm = _load_yaml(md_text[3:end]) or {}
            body = md_text[end + 4:].lstrip("\n")
            return fm, body
    return {}, md_text


def tools_to_toolset(tool_names):
    """A list of file-tool names → the CMA agent_toolset_20260401 structure."""
    return [{
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": False},
        "configs": [{"name": n, "enabled": True} for n in tool_names],
    }]


def find_skill(name: str):
    """Locate a skill dir by name anywhere under skills/ (skills are organized by category)."""
    for sm in (REPO / "skills").rglob("SKILL.md"):
        if sm.parent.name == name:
            return sm.parent
    return None


def resolve_skills(skill_names):
    """skill name → {type: custom, skill_ref: <path-relative-to-repo>}. Drift-checked elsewhere."""
    out = []
    for nm in skill_names or []:
        d = find_skill(nm)
        if d:
            out.append({"type": "custom", "skill_ref": str(d.relative_to(REPO))})
        else:
            print(f"  ! skill '{nm}' not found under skills/", file=sys.stderr)
    return out


def build_leaf(leaf: dict, model: str) -> dict:
    """One depth-1 subagent JSON from a cma.yaml leaf entry."""
    role = leaf.get("role", "critic")
    name = leaf["as"]
    # prompt: from expert md body, or inline prompt for synthetic leaves (packager)
    if "expert" in leaf:
        fm, body = parse_frontmatter((REPO / leaf["expert"]).read_text())
        prompt = body.strip()
        skills = resolve_skills(fm.get("skills"))
    else:
        prompt = (leaf.get("prompt") or "").strip()
        skills = []
    node = {
        "name": name,
        "model": model,
        "system": {"text": prompt},
        "tools": tools_to_toolset(ROLE_TOOLS[role]),
        "mcp_servers": [],
        "skills": skills,
        "callable_agents": [],          # depth-1: leaves never nest (CMA one-level rule)
    }
    if role == "reader" and leaf.get("schema"):
        node["output_schema"] = json.loads((REPO / leaf["schema"]).read_text())
    return node


def build_workflow(name: str, wf: dict, model: str, headless: str) -> dict:
    """One orchestrator + its leaves → the full CMA payload for `POST /v1/agents`."""
    fm, body = parse_frontmatter((REPO / wf["orchestrator"]).read_text())
    system = body.strip()
    if headless:
        system += "\n\n" + headless.strip()
    orch = {
        "name": fm.get("name", name),
        "model": model,
        "system": {"text": system},
        "tools": tools_to_toolset(ROLE_TOOLS["orchestrator"]),
        "mcp_servers": [],
        "skills": resolve_skills(fm.get("skills")),
        "callable_agents": [build_leaf(l, model) for l in wf.get("leaves", [])],
    }
    return orch


def main(argv):
    do_post = "--post" in argv
    model_override = None
    if "--model" in argv:
        model_override = argv[argv.index("--model") + 1]
    targets = [a for a in argv[1:] if not a.startswith("--") and a != model_override]

    manifest = _load_yaml(MANIFEST.read_text())
    model = model_override or _expand_env(str(manifest.get("model", "sonnet")))
    headless = manifest.get("headless_append", "")
    workflows = manifest.get("workflows", {})
    if targets:
        workflows = {k: v for k, v in workflows.items() if k in targets}

    for name, wf in workflows.items():
        payload = build_workflow(name, wf, model, headless)
        n_leaves = len(payload["callable_agents"])
        writers = [l["name"] for l in payload["callable_agents"]
                   if any(c["name"] in ("write", "edit") for ts in l["tools"] for c in ts["configs"])]
        print(f"\n===== workflow: {name}  (model={model}, leaves={n_leaves}, writers={writers}) =====")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if do_post:
            print(f"  [--post] would upload skills + POST /v1/agents for '{name}' "
                  f"(wire to anthropic SDK / deploy here)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
