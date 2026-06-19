---
name: osv-check
description: "Vulnerability scanner for Python requirements.txt against Google OSV API."
version: 1.0.0
author: Seeker.Bot + Seeker Agent
license: MIT
platforms: [windows, linux, macos]
prerequisites:
  commands: [python]
metadata:
  seeker_agent:
    tags: [security, vulnerabilities, scan, requirements, PyPI]
---

# OSV Check — Dependency Vulnerability Scanner

This skill audits the project's Python dependencies (`requirements.txt`) against Google's Open Source Vulnerability (OSV) database API. It surfaces CVEs, severity ratings, and recommended package versions to resolve security issues.

---

## Command Reference

Run the audit tool through the Seeker CLI:

```powershell
# Windows
& "E:\Seeker.Bot\.venv\Scripts\python.exe" "E:\Seeker.Bot\scripts\seeker_cli.py" osv_check

# Linux/macOS
E:/Seeker.Bot/.venv/bin/python E:/Seeker.Bot/scripts/seeker_cli.py osv_check
```

---

## Agent Usage Guidelines

Use this skill:
- When reviewing a project codebase or setting up a workspace.
- To audit the dependencies before shipping code or upgrading packages.
- When the user asks to check for security vulnerabilities or scan the repository.
