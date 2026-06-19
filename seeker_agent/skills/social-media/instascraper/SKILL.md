---
name: instascraper
description: "Instagram Media & Metadata Scraper with Obsidian integration."
version: 1.0.0
author: Seeker.Bot + Seeker Agent
license: MIT
platforms: [windows, linux, macos]
prerequisites:
  commands: [python]
metadata:
  seeker_agent:
    tags: [instagram, scraping, social-media, obsidian, markdown]
---

# InstaScraper — Instagram Media & Metadata Scraper

This skill allows the agent to scrape public Instagram profiles, download video posts (.mp4), extract metadata, and automatically generate structured Markdown notes directly inside the Obsidian Vault Inbox.

It runs locally using a cookie session to avoid WAF blocks and simulates human delays to prevent shadowbans.

---

## Command Reference

Run the script using the Seeker.Bot python environment:

```powershell
# Windows
& "E:\Seeker.Bot\.venv\Scripts\python.exe" "E:\Seeker.Bot\scripts\seeker_cli.py" instascraper <username> --limit <count>

# Linux/macOS
E:/Seeker.Bot/.venv/bin/python E:/Seeker.Bot/scripts/seeker_cli.py instascraper <username> --limit <count>
```

### Options:
* `<username>`: The Instagram profile name (e.g. `lukebuildsai` or `nousresearch`). Leading `@` signs are automatically stripped.
* `--limit <count>`: The maximum number of recent posts to scrape (default is 10).

---

## Obsidian Note Integration

Upon successful scraping, the command:
1. Downloads video posts to `E:/Seeker.Bot/Downloads/Instagram/<username>/`.
2. Generates Markdown notes in the Obsidian Vault Inbox: `D:\Obsidian\Segundo Cérebro\Segundo Cérebro\Inbox\`.
3. The note references the local media files using the path format: `![[file:///E:/Seeker.Bot/Downloads/Instagram/<username>/<file>.mp4]]`.

Use this skill to research targets, scrape creatives, or capture business intelligence on social media competitors.
