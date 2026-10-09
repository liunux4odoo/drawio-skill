"""List and find QwenPaw agents by scanning workspace directories.

Pure stdlib; no qwenpaw import. Reads each workspace's agent.json for
metadata and memory size.

Usage:
    python qwenpaw_agents.py                      # list all
    python qwenpaw_agents.py <keyword>            # find by id/name/description
    python qwenpaw_agents.py --json <keyword>?    # machine-readable output
"""
import argparse
import json
import pathlib
import sys

DEFAULT_ROOT = "/data/ai_work/qwenpaw-data/workspaces"


def discover_agents(root: str) -> list[dict]:
    agents = []
    root_path = pathlib.Path(root)
    if not root_path.is_dir():
        return agents
    for ws in sorted(root_path.iterdir()):
        if not ws.is_dir():
            continue
        agent_json = ws / "agent.json"
        if not agent_json.is_file():
            continue
        try:
            cfg = json.loads(agent_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        aid = cfg.get("id") or ws.name
        memory_dir = ws / "memory"
        mem_files = 0
        mem_bytes = 0
        if memory_dir.is_dir():
            for p in memory_dir.rglob("*"):
                if p.is_file():
                    mem_files += 1
                    mem_bytes += p.stat().st_size
        agents.append(
            {
                "id": aid,
                "name": cfg.get("name", ""),
                "description": cfg.get("description", ""),
                "workspace_dir": str(ws),
                "memory_files": mem_files,
                "memory_bytes": mem_bytes,
            }
        )
    return agents


def matches(agent: dict, keyword: str) -> bool:
    kw = keyword.lower()
    haystacks = [
        agent["id"].lower(),
        agent["name"].lower(),
        agent["description"].lower(),
        agent["workspace_dir"].lower(),
    ]
    return any(kw in h for h in haystacks)


def main() -> None:
    parser = argparse.ArgumentParser(description="List/find QwenPaw agents")
    parser.add_argument("keyword", nargs="?", default="", help="search keyword")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="workspaces root dir")
    args = parser.parse_args()

    agents = discover_agents(args.root)
    if args.keyword:
        agents = [a for a in agents if matches(a, args.keyword)]

    if args.json:
        print(json.dumps(agents, ensure_ascii=False, indent=1))
        return

    if not agents:
        print("No agents found." + (f" for keyword: {args.keyword}" if args.keyword else ""))
        return

    print(f"{'ID':<24} {'NAME':<20} {'MEM':>8}  DESCRIPTION")
    print("-" * 100)
    for a in agents:
        mem_mb = a["memory_bytes"] / 1024 / 1024
        desc = (a["description"] or "")[:60]
        print(f"{a['id']:<24} {a['name']:<20} {mem_mb:>6.2f}M  {desc}")


if __name__ == "__main__":
    main()
