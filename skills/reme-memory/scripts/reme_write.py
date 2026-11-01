"""Write into a QwenPaw-style ReMe memory vault (agent workspace or project .qwenpaw/).

Pure `reme` + stdlib; no qwenpaw import. Constructs a *writable* ReMe
instance: keeps `write`/`read`/`index_update`/`reindex`/`search` jobs but
still omits the `index_update_loop` background job, so the process writes
only when you explicitly ask it to (write → ingest → reindex), then exits.

Two targets:
  --agent <id>      → the agent's workspace (same vault QwenPaw uses)
  --project <dir>   → a project directory; the vault is <dir>/.qwenpaw
                      (the project-level L3 memory vault)

Usage:
    python reme_write.py --agent travel-assistant --name 签证补充 \
        --description "客户需要的补充材料" \
        --content "护照首页扫描件、在职证明、流水三个月。" \
        --path "memory/notes/visa-materials.md"
    python reme_write.py --project /path/to/proj --name deploy-runbook \
        --description "部署步骤" --content "1. build; 2. push; 3. restart." \
        --path "memory/notes/deploy.md"
    python reme_write.py --agent small_reactor --no-index --name scratch \
        --description "temp note" --content "just write, skip indexing"
"""
import argparse
import asyncio
import json
import pathlib
import sys

DEFAULT_ROOT = "/data/ai_work/qwenpaw-data/workspaces"
DEFAULT_VAULT_SUBDIR = ".qwenpaw"


def resolve_workspace(root: str, agent_ref: str) -> pathlib.Path:
    """Resolve agent id/workspace name to its workspace directory."""
    root_path = pathlib.Path(root)
    direct = root_path / agent_ref
    if direct.is_dir() and (direct / "agent.json").is_file():
        return direct
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


def load_agent_mem_config(agent_json_path: pathlib.Path) -> dict:
    """Read the agent's reme_light_memory_config for dirs + embedding config."""
    raw = json.loads(agent_json_path.read_text(encoding="utf-8"))
    return raw["running"]["reme_light_memory_config"]


def build_writable_config(workspace_dir: str, mem: dict) -> dict:
    """Writable ReMe config: write/read/index_update/reindex/search jobs.

    No `index_update_loop` background job — indexing happens only when the
    `index_update` job is invoked explicitly (write → ingest → reindex).
    """
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
        # One-shot ingest: scan watch dirs (daily_dir/digest_dir), diff vs
        # file_catalog, dispatch to update_index_step. This is what turns a
        # newly written file into searchable chunks.
        "index_update": {
            "backend": "base",
            "steps": [
                {
                    "backend": "init_changes_step",
                    "monitor_type": "file_store",
                    "monitor_name": "default",
                    "dispatch_steps": ["update_index_step"],
                },
            ],
        },
        "search": {
            "backend": "base",
            "steps": [{"backend": "search_step"}],
        },
        "write": {
            "backend": "base",
            "description": "Write a markdown file (create or overwrite) with name/description frontmatter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "content": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["path", "name", "description", "content"],
            },
            "steps": [{"backend": "write_step"}],
        },
        "read": {
            "backend": "base",
            "description": "Read a markdown file under the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
            "steps": [{"backend": "read_step"}],
        },
        "reindex": {
            "backend": "base",
            "description": "Rebuild search indexes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["all", "bm25", "embedding"],
                        "default": "all",
                    },
                },
            },
            "steps": [{"backend": "reindex_step"}],
        },
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
        # ReMe hard-codes log_dir="logs" relative to CWD; disable to avoid
        # dropping logs/ into the working directory.
        "log_to_console": False,
        "log_to_file": False,
    }


def resolve_vault(args) -> tuple[str, dict]:
    """Return (workspace_dir, mem_config) for --agent or --project."""
    if args.project:
        proj = pathlib.Path(args.project).expanduser().resolve()
        if not proj.is_dir():
            raise SystemExit(f"Project dir not found: {proj}")
        vault = proj / DEFAULT_VAULT_SUBDIR
        vault.mkdir(parents=True, exist_ok=True)
        # A project vault has no agent.json; use a neutral default memory
        # config (pure BM25, no embedding unless --embedding-config given).
        mem = {
            "metadata_dir": "mem_metadata",
            "session_dir": "mem_session",
            "mem_session_dir": "mem_agent",
            "resource_dir": "resource",
            "daily_dir": "memory",
            "digest_dir": "digest",
            "embedding_model_config": {},
        }
        if args.embedding_config:
            mem["embedding_model_config"] = json.loads(
                pathlib.Path(args.embedding_config).read_text(encoding="utf-8"))
        return str(vault), mem

    # --agent path: reuse the agent's own memory dirs + embedding config
    ws = resolve_workspace(args.root, args.agent)
    mem = load_agent_mem_config(ws / "agent.json")
    return str(ws), mem


async def run_write(workspace_dir: str, mem: dict, args) -> None:
    from reme import ReMe

    cfg = build_writable_config(workspace_dir, mem)
    app = ReMe(**cfg)
    try:
        await app.start()

        wresp = await app.run_job(
            "write",
            path=args.path,
            name=args.name,
            description=args.description,
            content=args.content,
        )
        ok = getattr(wresp, "success", None)
        ans = getattr(wresp, "answer", None)
        print(f"[write] {'OK' if ok else 'FAILED'}: {ans}")
        if not ok:
            sys.exit(2)

        if args.no_index:
            print("[skip] --no-index: not ingesting/reindexing")
            return

        # Ingest the new file (init_changes_step scans watch dirs)
        iresp = await app.run_job(
            "index_update",
            watch_dirs=["daily_dir", "digest_dir"],
            watch_suffixes=["md"],
        )
        ians = getattr(iresp, "answer", iresp)
        print(f"[index_update] {ians}")

        # Rebuild BM25/embedding indexes from ingested chunks
        rresp = await app.run_job("reindex", scope="all")
        rans = getattr(rresp, "answer", rresp)
        print(f"[reindex] {rans}")
    finally:
        await app.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write into a QwenPaw-style ReMe vault (agent workspace or project .qwenpaw/)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--agent", help="agent id or workspace name (writes agent workspace)")
    target.add_argument("--project", help="project directory (writes <dir>/.qwenpaw as L3 vault)")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="workspaces root dir (for --agent)")
    parser.add_argument("--embedding-config",
                        help="JSON file with embedding_model_config (optional, for --project)")
    parser.add_argument("--path", default="memory/notes/note.md",
                        help="vault-relative target path (default memory/notes/note.md)")
    parser.add_argument("--name", required=True, help="frontmatter name")
    parser.add_argument("--description", required=True, help="frontmatter description")
    parser.add_argument("--content", required=True, help="markdown body")
    parser.add_argument("--no-index", action="store_true",
                        help="write only; skip ingest+reindex")
    args = parser.parse_args()

    workspace_dir, mem = resolve_vault(args)
    asyncio.run(run_write(workspace_dir, mem, args))


if __name__ == "__main__":
    main()
