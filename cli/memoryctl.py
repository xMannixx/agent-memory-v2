#!/usr/bin/env python3
"""memoryctl — unified CLI for Memory Core v2.

B1 scope: episode, fact (read-only), stats, import.
Spec reference: §10.

Usage examples:
    memoryctl episode add "User asked about setup" --origin trusted_user
    memoryctl episode search "Nextcloud" --namespace dev --json
    memoryctl episode list --namespace dev --limit 10
    memoryctl episode stats --namespace dev --json

    memoryctl fact recall "server" --namespace dev --json
    memoryctl fact list --namespace dev --authority evidence
    memoryctl fact get f_1234567890abcdef --json

    memoryctl stats --namespace dev --json

    memoryctl import --from-v3 /path/to/old.db --namespace hermes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

# Ensure the src package is importable when run as a script.
_CLI_DIR = Path(__file__).resolve().parent
_SRC_DIR = _CLI_DIR.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR.parent))

from src.config import load_config
from src.router import StorageRouter
from src.episodes import EpisodeStore
from src.facts import FactStore
from src.importer import import_v3


def _json_output(data: Any) -> None:
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _plain_list(items: list, key: str = "content") -> None:
    """Print items in a simple list format."""
    for item in items:
        d = item.to_dict() if hasattr(item, "to_dict") else item
        print(f"  [{d.get('id', '?')}] {d.get(key, '')}")


# -- subcommand handlers ------------------------------------------------------

def cmd_episode_add(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = EpisodeStore(router)
    ep_id = store.add(
        namespace=args.namespace,
        content=args.content,
        role=args.role,
        origin=args.origin,
        session_id=args.session,
    )
    if args.json:
        _json_output({"id": ep_id})
    else:
        print(f"Episode added: {ep_id}")


def cmd_episode_search(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = EpisodeStore(router)
    results = store.search(args.namespace, args.query, limit=args.limit)
    if args.json:
        _json_output([e.to_dict() for e in results])
    else:
        print(f"Found {len(results)} episode(s):")
        _plain_list(results)


def cmd_episode_list(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = EpisodeStore(router)
    results = store.list_recent(args.namespace, limit=args.limit)
    if args.json:
        _json_output([e.to_dict() for e in results])
    else:
        print(f"Recent {len(results)} episode(s):")
        _plain_list(results)


def cmd_episode_stats(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = EpisodeStore(router)
    stats = store.stats(args.namespace)
    if args.json:
        _json_output(stats)
    else:
        print(f"Episodes in '{args.namespace}':")
        print(f"  Total: {stats['total']}")
        print(f"  Unconsumed: {stats['unconsumed']}")
        if stats["by_role"]:
            print("  By role:")
            for role, count in sorted(stats["by_role"].items()):
                print(f"    {role}: {count}")


def cmd_fact_recall(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = FactStore(router)
    results = store.recall(
        args.namespace, args.query, limit=args.limit,
        authority_class=args.authority,
    )
    if args.json:
        _json_output([f.to_dict() for f in results])
    else:
        print(f"Found {len(results)} fact(s):")
        _plain_list(results)


def cmd_fact_list(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = FactStore(router)
    results = store.list_facts(
        args.namespace, authority_class=args.authority, limit=args.limit,
    )
    if args.json:
        _json_output([f.to_dict() for f in results])
    else:
        print(f"Listing {len(results)} fact(s):")
        _plain_list(results)


def cmd_fact_get(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    store = FactStore(router)
    fact = store.get_fact(args.namespace, args.fact_id)
    if fact is None:
        print(f"Fact not found: {args.fact_id}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        _json_output(fact.to_dict())
    else:
        d = fact.to_dict()
        for key, value in d.items():
            print(f"  {key}: {value}")


def cmd_stats(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    ep_store = EpisodeStore(router)
    fact_store = FactStore(router)
    ep_stats = ep_store.stats(args.namespace)
    fact_stats = fact_store.stats(args.namespace)
    combined = {
        "namespace": args.namespace,
        "episodes": ep_stats,
        "facts": fact_stats,
    }
    if args.json:
        _json_output(combined)
    else:
        print(f"=== Stats for '{args.namespace}' ===")
        print(f"Episodes: {ep_stats['total']} "
              f"({ep_stats['unconsumed']} unconsumed)")
        print(f"Active facts: {fact_stats['active']}")
        if fact_stats["by_lane"]:
            for lane, count in sorted(fact_stats["by_lane"].items()):
                print(f"  {lane}: {count}")


def cmd_import(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    router = StorageRouter(config)
    result = import_v3(
        router, args.from_v3, args.namespace, dry_run=args.dry_run,
    )
    if args.json:
        _json_output(result.to_dict())
    else:
        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"{prefix}Import from {args.from_v3} → "
              f"namespace '{args.namespace}':")
        for table, count in sorted(result.counts.items()):
            skipped = result.skipped.get(table, 0)
            skip_str = f" (skipped {skipped})" if skipped else ""
            print(f"  {table}: {count}{skip_str}")
        if result.errors:
            print("Errors:")
            for err in result.errors:
                print(f"  {err}")


# -- argument parser ----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memoryctl",
        description="Memory Core v2 — CLI",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config.toml (default: auto-discover)",
    )
    parser.add_argument(
        "--namespace", "-n", default="default",
        help="Target namespace (default: 'default')",
    )
    parser.add_argument(
        "--json", action="store_true", default=False,
        help="Output in JSON format",
    )

    sub = parser.add_subparsers(dest="command")

    # -- episode --------------------------------------------------------------
    ep = sub.add_parser("episode", help="Episode log commands")
    ep_sub = ep.add_subparsers(dest="episode_command")

    ep_add = ep_sub.add_parser("add", help="Add an episode")
    ep_add.add_argument("content", help="Episode content")
    ep_add.add_argument("--role", default="user",
                        help="Role (user|assistant|tool|system)")
    ep_add.add_argument("--origin", default="trusted_user",
                        help="Origin vocabulary term")
    ep_add.add_argument("--session", default=None, help="Session ID")

    ep_search = ep_sub.add_parser("search", help="Search episodes")
    ep_search.add_argument("query", help="Search query")
    ep_search.add_argument("--limit", type=int, default=20)

    ep_list = ep_sub.add_parser("list", help="List recent episodes")
    ep_list.add_argument("--limit", type=int, default=50)

    ep_stats = ep_sub.add_parser("stats", help="Episode statistics")

    # -- fact -----------------------------------------------------------------
    ft = sub.add_parser("fact", help="Fact commands (read-only in B1)")
    ft_sub = ft.add_subparsers(dest="fact_command")

    ft_recall = ft_sub.add_parser("recall", help="Search facts")
    ft_recall.add_argument("query", help="Search query")
    ft_recall.add_argument("--limit", type=int, default=10)
    ft_recall.add_argument("--authority", default=None,
                           help="Filter by authority class")

    ft_list = ft_sub.add_parser("list", help="List facts")
    ft_list.add_argument("--limit", type=int, default=50)
    ft_list.add_argument("--authority", default=None,
                         help="Filter by authority class")

    ft_get = ft_sub.add_parser("get", help="Get a single fact")
    ft_get.add_argument("fact_id", help="Fact ID")

    # -- stats ----------------------------------------------------------------
    sub.add_parser("stats", help="Combined statistics")

    # -- import ---------------------------------------------------------------
    imp = sub.add_parser("import", help="Import from v3.6")
    imp.add_argument("--from-v3", required=True,
                     help="Path to v3.6 memory.db")
    imp.add_argument("--dry-run", action="store_true", default=False,
                     help="Report without writing")

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        ("episode", "add"): cmd_episode_add,
        ("episode", "search"): cmd_episode_search,
        ("episode", "list"): cmd_episode_list,
        ("episode", "stats"): cmd_episode_stats,
        ("fact", "recall"): cmd_fact_recall,
        ("fact", "list"): cmd_fact_list,
        ("fact", "get"): cmd_fact_get,
        ("stats", None): cmd_stats,
        ("import", None): cmd_import,
    }

    if args.command in ("episode", "fact"):
        sub_cmd = getattr(args, f"{args.command}_command", None)
        key = (args.command, sub_cmd)
    else:
        key = (args.command, None)

    handler = dispatch.get(key)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
