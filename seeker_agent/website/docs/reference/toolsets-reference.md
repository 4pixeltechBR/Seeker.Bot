---
sidebar_position: 4
title: "Toolsets Reference"
description: "Reference for SeekerAgent core, composite, platform, and dynamic toolsets"
---

# Toolsets Reference

Toolsets are named bundles of tools that control what the agent can do. They're the primary mechanism for configuring tool availability per platform, per session, or per task.

## How Toolsets Work

Every tool belongs to exactly one toolset. When you enable a toolset, all tools in that bundle become available to the agent. Toolsets come in three kinds:

- **Core** — A single logical group of related tools (e.g., `file` bundles `read_file`, `write_file`, `patch`, `search_files`)
- **Composite** — Combines multiple core toolsets for a common scenario (e.g., `debugging` bundles file, terminal, and web tools)
- **Platform** — A complete tool configuration for a specific deployment context (e.g., `seeker_agent-cli` is the default for interactive CLI sessions)

## Configuring Toolsets

### Per-session (CLI)

```bash
seeker_agent chat --toolsets web,file,terminal
seeker_agent chat --toolsets debugging        # composite — expands to file + terminal + web
seeker_agent chat --toolsets all              # everything
```

### Per-platform (config.yaml)

```yaml
toolsets:
  - seeker_agent-cli          # default for CLI
  # - seeker_agent-telegram   # override for Telegram gateway
```

### Interactive management

```bash
seeker_agent tools                            # curses UI to enable/disable per platform
```

Or in-session:

```
/tools list
/tools disable browser
/tools enable homeassistant
```

## Core Toolsets

| Toolset | Tools | Purpose |
|---------|-------|---------|
| `browser` | `browser_back`, `browser_cdp`, `browser_click`, `browser_console`, `browser_dialog`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vision`, `web_search` | Core browser automation. Includes `web_search` as a fallback for quick lookups. `browser_cdp` and `browser_dialog` are gated at runtime — registered only when a CDP endpoint is reachable at session start (via `/browser connect`, `browser.cdp_url` config, Browserbase, or Camofox). `browser_dialog` works together with the `pending_dialogs` and `frame_tree` fields that `browser_snapshot` adds when a CDP supervisor is attached. |
| `clarify` | `clarify` | Ask the user a question when the agent needs clarification. |
| `code_execution` | `execute_code` | Run Python scripts that call SeekerAgent tools programmatically. |
| `cronjob` | `cronjob` | Schedule and manage recurring tasks. |
| `debugging` | composite (`file` + `terminal` + `web`) | Debug bundle — file, process/terminal, web extract/search. |
| `delegation` | `delegate_task` | Spawn isolated subagent instances for parallel work. |
| `discord` | `discord` | Core Discord text/embed/DM actions (gateway-only). Active on the `seeker_agent-discord` toolset. |
| `discord_admin` | `discord_admin` | Discord moderation (bans, role changes, channel management). Active on the `seeker_agent-discord` toolset; requires the bot to hold the relevant Discord permissions. |
| `feishu_doc` | `feishu_doc_read` | Read Feishu/Lark document content. Used by the Feishu document-comment intelligent-reply handler. |
| `feishu_drive` | `feishu_drive_add_comment`, `feishu_drive_list_comments`, `feishu_drive_list_comment_replies`, `feishu_drive_reply_comment` | Feishu/Lark drive comment operations. Scoped to the comment agent; not exposed on `seeker_agent-cli` or other messaging toolsets. |
| `file` | `patch`, `read_file`, `search_files`, `write_file` | File reading, writing, searching, and editing. |
| `homeassistant` | `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services` | Smart home control via Home Assistant. Only available when `HASS_TOKEN` is set. |
| `computer_use` | `computer_use` | Background macOS desktop control via cua-driver — does not steal cursor/focus. Works with any tool-capable model. macOS only; requires `cua-driver` on `$PATH`. |
| `image_gen` | `image_generate` | Text-to-image generation via FAL.ai (with opt-in OpenAI / xAI backends). |
| `video_gen` | `video_generate` | Text-to-video and image-to-video via plugin-registered backends (xAI Grok-Imagine, FAL.ai Veo 3.1 / Pixverse v6 / Kling O3). Pass `image_url` to animate an image; omit it for text-to-video. |
| `kanban` | `kanban_block`, `kanban_comment`, `kanban_complete`, `kanban_create`, `kanban_heartbeat`, `kanban_link`, `kanban_list`, `kanban_show`, `kanban_unblock` | Multi-agent coordination tools. Registered for dispatcher-spawned task workers (`HERMES_KANBAN_TASK`) and for profiles that explicitly enable the `kanban` toolset. Workers mark tasks done, block, heartbeat, comment, and create/link follow-up tasks; orchestrator profiles additionally get board-routing tools like list/unblock. |
| `memory` | `memory` | Persistent cross-session memory management. |
| `messaging` | `send_message` | Send messages to other platforms (Telegram, Discord, etc.) from within a session. |
| `moa` | `mixture_of_agents` | Multi-model consensus via Mixture of Agents. |
| `safe` | `image_generate`, `vision_analyze`, `web_extract`, `web_search` (via `includes`) | Read-only research + media generation. No file writes, no terminal, no code execution. |
| `search` | `web_search` | Web search only (without extract). |
| `session_search` | `session_search` | Search past conversation sessions. |
| `skills` | `skill_manage`, `skill_view`, `skills_list` | Skill CRUD and browsing. |
| `spotify` | `spotify_albums`, `spotify_devices`, `spotify_library`, `spotify_playback`, `spotify_playlists`, `spotify_queue`, `spotify_search` | Native Spotify control (playback, queue, search, playlists, albums, library). Registered by the bundled `spotify` plugin. |
| `terminal` | `process`, `terminal` | Shell command execution and background process management. |
| `todo` | `todo` | Task list management within a session. |
| `tts` | `text_to_speech` | Text-to-speech audio generation. |
| `vision` | `vision_analyze` | Image analysis via vision-capable models. |
| `video` | `video_analyze` | Video analysis and understanding tools (opt-in, not in the default toolset — add explicitly via `--toolsets`). |
| `web` | `web_extract`, `web_search` | Web search and page content extraction. |
| `x_search` | `x_search` | Search X (Twitter) posts and threads via xAI's built-in `x_search` Responses tool. Off by default; opt in via `seeker_agent tools`. Schema only registered when xAI credentials (SuperGrok OAuth or `XAI_API_KEY`) are configured. |
| `yuanbao` | `yb_query_group_info`, `yb_query_group_members`, `yb_search_sticker`, `yb_send_dm`, `yb_send_sticker` | Yuanbao DM/group actions and sticker search. Registered only on `seeker_agent-yuanbao`. |

## Platform Toolsets

Platform toolsets define the complete tool configuration for a deployment target. Most messaging platforms use the same set as `seeker_agent-cli`:

| Toolset | Differences from `seeker_agent-cli` |
|---------|-------------------------------|
| `seeker_agent-cli` | Full toolset — the default for interactive CLI sessions. Includes file, terminal, web, browser, memory, skills, vision, image_gen, todo, tts, delegation, code_execution, cronjob, session_search, clarify, and `safe` (read-only) bundles plus the standard messaging tools. |
| `seeker_agent-acp` | Drops `clarify`, `cronjob`, `image_generate`, `send_message`, `text_to_speech`, and all four Home Assistant tools. Focused on coding tasks in IDE context. |
| `seeker_agent-api-server` | Drops `clarify`, `send_message`, and `text_to_speech`. Keeps everything else — suitable for programmatic access where user interaction isn't possible. |
| `seeker_agent-cron` | Same as `seeker_agent-cli`. |
| `seeker_agent-telegram` | Same as `seeker_agent-cli`. |
| `seeker_agent-discord` | Adds `discord` and `discord_admin` on top of `seeker_agent-cli`. |
| `seeker_agent-slack` | Same as `seeker_agent-cli`. |
| `seeker_agent-whatsapp` | Same as `seeker_agent-cli`. |
| `seeker_agent-signal` | Same as `seeker_agent-cli`. |
| `seeker_agent-matrix` | Same as `seeker_agent-cli`. |
| `seeker_agent-mattermost` | Same as `seeker_agent-cli`. |
| `seeker_agent-email` | Same as `seeker_agent-cli`. |
| `seeker_agent-sms` | Same as `seeker_agent-cli`. |
| `seeker_agent-bluebubbles` | Same as `seeker_agent-cli`. |
| `seeker_agent-dingtalk` | Same as `seeker_agent-cli`. |
| `seeker_agent-feishu` | Adds the five `feishu_doc_*` / `feishu_drive_*` tools (only used by the document-comment handler, not the regular chat adapter). |
| `seeker_agent-qqbot` | Same as `seeker_agent-cli`. |
| `seeker_agent-wecom` | Same as `seeker_agent-cli`. |
| `seeker_agent-wecom-callback` | Same as `seeker_agent-cli`. |
| `seeker_agent-weixin` | Same as `seeker_agent-cli`. |
| `seeker_agent-yuanbao` | Adds the five `yb_*` tools (DM/group/sticker) on top of `seeker_agent-cli`. |
| `seeker_agent-homeassistant` | Same as `seeker_agent-cli` (the Home Assistant tools are already present by default and activate when `HASS_TOKEN` is set). |
| `seeker_agent-webhook` | Same as `seeker_agent-cli`. |
| `seeker_agent-gateway` | Internal gateway orchestrator toolset — union of every `seeker_agent-<platform>` toolset; used when the gateway needs to accept any message source. |

## Dynamic Toolsets

### MCP server toolsets

Each configured MCP server generates a `mcp-<server>` toolset at runtime. For example, if you configure a `github` MCP server, a `mcp-github` toolset is created containing all tools that server exposes.

```yaml
# config.yaml
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
```

This creates a `mcp-github` toolset you can reference in `--toolsets` or platform configs.

### Plugin toolsets

Plugins can register their own toolsets via `ctx.register_tool()` during plugin initialization. These appear alongside built-in toolsets and can be enabled/disabled the same way.

### Custom toolsets

Define custom toolsets in `config.yaml` to create project-specific bundles:

```yaml
toolsets:
  - seeker_agent-cli
custom_toolsets:
  data-science:
    - file
    - terminal
    - code_execution
    - web
    - vision
```

### Wildcards

- `all` or `*` — expands to every registered toolset (built-in + dynamic + plugin)

## Relationship to `seeker_agent tools`

The `seeker_agent tools` command provides a curses-based UI for toggling individual tools on or off per platform. This operates at the tool level (finer than toolsets) and persists to `config.yaml`. Disabled tools are filtered out even if their toolset is enabled.

See also: [Tools Reference](./tools-reference.md) for the complete list of individual tools and their parameters.
