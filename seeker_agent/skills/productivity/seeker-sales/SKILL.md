---
name: seeker-sales
description: "B2B Sales CRM & Event Radar statistics query utility."
version: 1.0.0
author: Seeker.Bot + Seeker Agent
license: MIT
platforms: [windows, linux, macos]
prerequisites:
  commands: [python]
metadata:
  seeker_agent:
    tags: [sales, leads, crm, b2b, radar, events]
---

# Seeker Sales — B2B Sales CRM & Event Radar

This skill provides direct CLI access to the Seeker.Bot B2B sales leads CRM (backed by SQLite) and the Event Radar database. It allows querying qualified leads, viewing the sales pipeline funnel, retrieving logs for a specific lead, and checking upcoming business events.

---

## Command Reference

Run the native module using the Seeker environment:

```powershell
# Windows
& "E:\Seeker.Bot\.venv\Scripts\python.exe" -m src.skills.seeker_sales [options]

# Linux/macOS
E:/Seeker.Bot/.venv/bin/python -m src.skills.seeker_sales [options]
```

### Options:

* `--funnel`: Returns the count of leads in each stage of the sales pipeline (NOVO, CONTATADO, PROPOSTA, NEGOCIANDO, FECHADO_GANHO, FECHADO_PERDIDO, GELADO).
* `--window <months>`: Searches leads with events happening in the specified window of months (e.g. `--window 6`).
  * Add `--city <name>` to filter by city name (e.g. `--city Caldas`).
  * Add `--top <count>` to limit to the top N priorities.
* `--activity-log <target_key>`: Retrieves the full history of communications and events for a specific lead key.
* `--radar-stats`: Returns the statistics of upcoming business events captured by the Event Radar.
* `--json`: Appended to format the output as structured JSON instead of human-readable text.

---

## Agent Usage Guidelines

Use this skill when:
- The user asks about sales progress, lead status, or conversion rates.
- You need to search for qualified target accounts in specific cities.
- You need to review client interaction logs before writing custom proposals.
