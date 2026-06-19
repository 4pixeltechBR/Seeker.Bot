---
name: microsoft-graph
description: "Send emails via Microsoft Outlook using Microsoft Graph API."
version: 1.0.0
author: Seeker.Bot + Seeker Agent
license: MIT
platforms: [windows, linux, macos]
prerequisites:
  commands: [python]
metadata:
  seeker_agent:
    tags: [email, outlook, microsoft, graph, send]
---

# Microsoft Graph — Outlook Email Client

This skill allows the agent to send emails through the Microsoft Outlook service using the Microsoft Graph API. It is configured via environment variables and runs as a CLI command.

---

## Environment Variables (MANDATORY)

To authenticate, the user must set the following environment variables on the system:

* `MICROSOFT_ACCESS_TOKEN`: A static OAuth access token (overrides client credentials).
* OR (Azure AD App Credentials):
  * `MICROSOFT_CLIENT_ID`: The application (client) ID from Azure portal.
  * `MICROSOFT_CLIENT_SECRET`: The client secret value from Azure portal.
  * `MICROSOFT_TENANT_ID`: The Directory (tenant) ID (defaults to `common` if omitted).
  * `MICROSOFT_SENDER_EMAIL`: (Required for application permissions) The email address of the sending user account.

---

## Command Reference

Send an email via Seeker CLI:

```powershell
# Windows
& "E:\Seeker.Bot\.venv\Scripts\python.exe" "E:\Seeker.Bot\scripts\seeker_cli.py" msgraph send --to <recipient> --subject <subject> --body <body>

# Linux/macOS
E:/Seeker.Bot/.venv/bin/python E:/Seeker.Bot/scripts/seeker_cli.py msgraph send --to <recipient> --subject <subject> --body <body>
```

### Options:
* `--to`: Recipient email address.
* `--subject`: The subject of the email.
* `--body`: The body text of the email.
