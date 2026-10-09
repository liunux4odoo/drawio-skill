"""Search one QwenPaw agent's ReMe memory index.

Pure `reme` + stdlib; no qwenpaw import. Replicates the config that
`qwenpaw.agents.memory.reme_config.get_reme_app_config()` builds, but keeps
only the `search` job (no `index_update_loop`), so it never writes to the
index and starts cold in ~1-2s.

Usage:
    python qwenpaw_search.py --agent <agent_id> "<query>"
    python qwenpaw_search.py --agent travel-assistant "签证材料清单"
    python qwenpaw_search.py --agent QwenPaw_QA_Agent_0.2 --limit 5 "workbuddy"
"""
import argparse
import asyncio
import json
import pathlib
import sys

DEFAULT_ROOT = "/data/ai_work/qwenpaw-data/workspaces"


def resolve_workspace(root: str, agent_ref: str) -> pathlib.Path:
    """Resolve agent id/workspace name to its workspace directory."""
    root_path = pathlib.Path(root)
    # 1. exact directory name
    direct = root_path / agent_ref
    if direct.is_dir() and (direct / "agent.json").is_file():
        return direct
    # 2. scan agent.json ids
    if root_path.is_dir():
        for ws in root_path.iterdir():
            if not ws.is_dir():
                continue
            agent_json = ws / "agent.json"
            if not agent_json.is_file():
                continue
            try:
                cfg = json.loads(agent_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            if cfg.get("id") == agent_ref:
                return ws
    raise SystemExit(f"Agent not found: {agent_ref} (under {root})")


def build_minimal_config(workspace_dir: str, agent_json_path: pathlib.Path) -> dict:
    """Replicate get_reme_app_config() without importing qwenpaw.

    Only the pieces needed for `search` are kept; background write jobs are
    omitted so no index writes happen.
    """
    raw = json.loads(agent_json_path.read_text(encoding="utf-8"))
    mem = raw["running"]["reme_light_memory_config"]
    emb = mem.get("embedding_model_config", {})

    components = {
        "tokenizer": {"default": {"backend": "regex"}},
        "keyword_index": {"default": {"backend": "bm25", "tokenizer": "default"}},
        "file_store": {
            "default": {
                "backend": "local",
                "store_name": "local",
                "keyword_index": "default",
                "file_graph": "default",
            }
        },
        "file_graph": {"default": {"backend": "local"}},
        "file_chunker": {
            "markdown": {"backend": "markdown", "supported_extensions": ["md"]},
            "default": {"backend": "default", "supported_extensions": ["jsonl"]},
        },
    }

    # embedding config if enabled
    if emb.get("model_name") and emb.get("api_key"):
        components["as_embedding"] = {
            "default": {
                "backend": emb.get("backend", "openai"),
                "model": emb["model_name"],
                "dimensions": emb.get("dimensions", 1024),
                "credential": {
                    "api_key": emb["api_key"],
                    "base_url": emb.get("base_url", ""),
                },
                "parameters": {},
            }
        }
        components["embedding_store"] = {
            "default": {
                "backend": "local",
                "as_embedding": "default",
                "enable_cache": emb.get("enable_cache", True),
                "max_cache_size": emb.get("max_cache_size", 3000),
                "max_input_length": emb.get("max_input_length", 8192),
                "max_batch_size": emb.get("max_batch_size", 10),
                "health_check_timeout": emb.get("health_check_timeout", 15.0),
            }
        }
        components["file_store"]["default"]["embedding_store"] = "default"
    else:
        components["file_store"]["default"]["embedding_store"] = ""

    jobs = {
        "search": {
            "backend": "base",
            "steps": [{"backend": "search_step"}],
        }
    }

    return {
        "plugins": [],
        "service": {"backend": "http", "enable_serve": False},
        "jobs": jobs,
        "components": components,
        "workspace_dir": workspace_dir,
        "metadata_dir": mem.get("metadata_dir", "mem_metadata"),
        "session_dir": mem.get("session_dir", "mem_session"),
        "mem_session_dir": mem.get("mem_session_dir", "mem_agent"),
        "resource_dir": mem.get("resource_dir", "resource"),
        "daily_dir": mem.get("daily_dir", "memory"),
        "digest_dir": mem.get("digest_dir", "digest"),
        "language": "zh",
        "timezone": "Asia/Shanghai",
        "enable_logo": False,
        # ReMe's Application.__init__ hard-codes log_dir="logs" (relative to
        # CWD) and only reads log_to_console/log_to_file. Disable file+console
        # logging so running the skill never drops logs/ into the repo.
        "log_to_console": False,
        "log_to_file": False,
    }


async def search(workspace_dir: str, agent_json_path: pathlib.Path,
                 query: str, limit: int) -> None:
    from reme import ReMe

    cfg = build_minimal_config(workspace_dir, agent_json_path)
    app = ReMe(**cfg)
    try:
        await app.start()
        resp = await app.run_job("search", query=query, limit=limit)
        ans = getattr(resp, "answer", None)
        if isinstance(ans, str) and ans.strip():
            print(ans)
        else:
            print("(no results)")
    finally:
        await app.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Search a QwenPaw agent's memory")
    parser.add_argument("--agent", required=True, help="agent id or workspace name")
    parser.add_argument("query", help="search query")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="workspaces root dir")
    parser.add_argument("--limit", type=int, default=3, help="max results (default 3)")
    args = parser.parse_args()

    ws = resolve_workspace(args.root, args.agent)
    asyncio.run(search(str(ws), ws / "agent.json", args.query, args.limit))


if __name__ == "__main__":
    main()
