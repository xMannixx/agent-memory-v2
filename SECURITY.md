# Security Policy

## Supported Versions

Memory Core v2 aims to be a highly secure foundation for agentic memory. We provide security updates for the current major version.

| Version | Supported          |
| ------- | ------------------ |
| 2.x.x   | :white_check_mark: |
| 1.x.x   | :x:                |

## Reporting a Vulnerability

Because Memory Core v2 functions as the "Immune System" against prompt injection and unauthorized memory writes, we take security vulnerabilities extremely seriously.

If you discover a vulnerability—particularly one that allows an LLM to bypass the deterministic Gate Pipeline (e.g., bypassing schema checks, spoofing audit logs, or injecting malicious payloads)—please **do not** open a public issue.

Instead, please report it privately:
1. Contact the repository owner via their public contact channels or GitHub private vulnerability reporting.
2. Provide a detailed Proof of Concept (PoC) demonstrating how the invariant is broken.

We will acknowledge receipt within 48 hours and work with you to patch the issue before public disclosure.
