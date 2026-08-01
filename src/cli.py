"""Command Line Interface for Memory Core v2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from .audit import AuditLog
from .config import load_config
from .consolidator import Consolidator
from .queue import ProposalQueue
from .router import StorageRouter


def main(args: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Memory Core v2 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # init
    init_p = subparsers.add_parser("init", help="Initialize database for a namespace")
    init_p.add_argument("namespace", help="Namespace to initialize")
    
    # db path
    db_p = subparsers.add_parser("db", help="Database operations")
    db_subs = db_p.add_subparsers(dest="db_cmd", required=True)
    db_path_p = db_subs.add_parser("path", help="Get DB path")
    db_path_p.add_argument("namespace", help="Namespace")
    
    # queue
    q_p = subparsers.add_parser("queue", help="Proposal Queue operations")
    q_subs = q_p.add_subparsers(dest="q_cmd", required=True)
    
    q_ls_p = q_subs.add_parser("ls", help="List pending proposals")
    q_ls_p.add_argument("namespace", help="Namespace")
    
    q_app_p = q_subs.add_parser("approve", help="Approve a proposal")
    q_app_p.add_argument("namespace", help="Namespace")
    q_app_p.add_argument("id", help="Proposal ID")
    q_app_p.add_argument("--by", default=os.environ.get("USER", "cli"), help="Operator identity")
    
    q_rej_p = q_subs.add_parser("reject", help="Reject a proposal")
    q_rej_p.add_argument("namespace", help="Namespace")
    q_rej_p.add_argument("id", help="Proposal ID")
    q_rej_p.add_argument("--by", default=os.environ.get("USER", "cli"), help="Operator identity")
    
    # audit
    aud_p = subparsers.add_parser("audit", help="Tail the audit log")
    aud_p.add_argument("namespace", help="Namespace")
    aud_p.add_argument("-n", "--lines", type=int, default=10, help="Number of entries")
    
    # run
    run_p = subparsers.add_parser("run", help="Run the consolidator loop")
    run_p.add_argument("namespace", help="Namespace")
    run_p.add_argument("--api-key", help="OpenAI API Key (or set OPENAI_API_KEY env var)")

    parsed = parser.parse_args(args)
    config = load_config()
    router = StorageRouter(config)
    audit = AuditLog(router)
    
    if parsed.command == "init":
        # connect automatically initializes schema
        router.connect(parsed.namespace)
        print(f"Initialized database for namespace '{parsed.namespace}'.")
        
    elif parsed.command == "db":
        if parsed.db_cmd == "path":
            print(router._resolve_path(parsed.namespace))
            
    elif parsed.command == "queue":
        queue = ProposalQueue(router, config, audit)
        if parsed.q_cmd == "ls":
            pending = queue.list_pending(parsed.namespace)
            if not pending:
                print("No pending proposals.")
            for p in pending:
                print(f"ID: {p.id}")
                print(f"Type: {p.proposal_type}")
                print(f"Payload: {json.dumps(p.payload, ensure_ascii=False)}")
                print("-" * 40)
        elif parsed.q_cmd == "approve":
            queue.approve(parsed.namespace, parsed.id, parsed.by)
            print(f"Approved {parsed.id}.")
        elif parsed.q_cmd == "reject":
            queue.reject(parsed.namespace, parsed.id, parsed.by)
            print(f"Rejected {parsed.id}.")
            
    elif parsed.command == "audit":
        conn = router.connect(parsed.namespace)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, ts, op, accepted, reason, metadata "
            "FROM memory_audit ORDER BY id DESC LIMIT ?",
            (parsed.lines,)
        )
        rows = cursor.fetchall()
        for r in reversed(rows):
            status = "SUCCESS" if r[3] else "FAILURE"
            reason = r[4] or "N/A"
            print(f"[{r[1]}] {r[2]} - {status} ({reason}) | {r[5]}")
            
    elif parsed.command == "run":
        api_key = parsed.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: --api-key or OPENAI_API_KEY environment variable required for OpenAI adapter.", file=sys.stderr)
            return 1
            
        try:
            from src.adapters.openai_provider import OpenAILlm
        except ImportError:
            print("Error: openai package not installed. Run 'pip install memory-core[openai]'", file=sys.stderr)
            return 1
            
        llm = OpenAILlm(api_key=api_key)
        consolidator = Consolidator(router, config, llm)
        stats = consolidator.run(parsed.namespace)
        print("Consolidation Run Complete:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
