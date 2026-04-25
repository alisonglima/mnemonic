---
name: using-mnemonic
description: Use when the user asks you to remember something, save a preference, or when you learn important context that should persist across sessions. Symptoms include "remember that I prefer", "save this preference", or "keep this in mind for next time".
---

# Using Mnemonic

## Overview

Mnemonic is a local-first memory infrastructure for AI agents. It provides a persistent, versioned, and searchable memory layer using SQLite (and optionally Qdrant for vector search).

As an AI agent, you must use Mnemonic to store important facts, decisions, user preferences, architectural notes, and any context that should persist across sessions.

## When to Use

**Remember (create/update):**
- After making a significant architectural or design decision
- User states a preference about how they work
- Discovering something important about the codebase or tools
- When you solve a complex bug or figure out a tricky configuration

**Recall (search/retrieve):**
- Starting a new session → recall relevant context
- User asks "what did we decide about X?"
- Need to check if a decision was already made
- Looking for known issues or patterns

**Forget (delete/archive):**
- User wants to remove outdated or incorrect memories
- Cleaning up duplicated or irrelevant entries

## Memory Types

When using `memory.write`, use the `type` parameter to classify the memory. Here are the standard types:

| Type | Use For | Example |
|------|---------|---------|
| `architectural-decision` | System architecture choices | "Using PostgreSQL with read replicas for scaling" |
| `design-decision` | UI/UX decisions | "Card layout for dashboard, 3 columns on desktop" |
| `learning` | Lessons and discoveries | "Bun's native TS support removes build step need" |
| `user-preference` | User preferences | "User prefers dark mode, tabs not spaces" |
| `project-preference` | Team conventions | "We use conventional commits, PR reviews required" |
| `issue` | Known problems | "Rate limiting not implemented yet, tracking in #42" |
| `context` | General context (default) | "Project started Feb 2026, MVP target Q2" |
| `recurring-pattern` | Reusable patterns | "Error handling: wrap in try/catch, return {error}" |
| `conventions-pattern` | Coding standards | "Use named exports, avoid default exports" |

## Core Pattern

When asked to remember something, **DO NOT** say you don't have persistent storage or suggest adding it to `AGENTS.md` or `CLAUDE.md`. Instead, use the `memory.write` MCP tool.

### Example: Saving a Preference

**Partner:** "I want you to remember that I prefer using TypeScript in all my projects. Save this preference."

**You:** "Saving your preference..."
[Dispatch `memory.write` tool]

```json
memory.write({
  "content": "The user prefers using TypeScript in all their projects.",
  "type": "user-preference",
  "namespace": "user:preferences",
  "scope_id": "language",
  "source": "agent",
  "tags": ["typescript", "preferences"]
})
```

## Rationalizations

| Excuse | Reality |
|--------|---------|
| "I don't have persistent storage between conversations" | You DO have persistent storage via the `memory.write` MCP tool. |
| "I'll add it to AGENTS.md or CLAUDE.md" | Use `memory.write` instead. Mnemonic is the dedicated memory layer. |
| "I'll remember that for this session" | The user wants it remembered across sessions. Use `memory.write`. |

## Quick Reference

| Operation | Tool | Example Usage |
|-----------|------|---------------|
| Save a fact | `memory.write` | `memory.write({ content: "...", type: "architectural-decision", namespace: "project:fluxo-erp", scope_id: "architecture", source: "agent" })` |
| Search memory | `memory.search` | `memory.search({ query: "multi-tenancy RLS", namespace: "project:fluxo-erp" })` |
| Update record | `memory.update` | `memory.update({ id: "...", expected_version: 1, content: "..." })` |
| Add tags | `memory.add_tags` | `memory.add_tags({ id: "...", tags: ["new-tag"] })` |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Saying "I don't have persistent storage" | Use the `memory.write` tool to save the information. |
| Suggesting `AGENTS.md` for user preferences | Use `memory.write` with `namespace: "user:preferences"`. |
| Updating without `expected_version` | Always use `memory.get` first to get the current `version`, then pass it as `expected_version` to `memory.update`. |
| Worrying about Qdrant/Ollama being "down" | Mnemonic works perfectly fine in SQLite-only mode. Ignore the "down" status for these services in `memory.health`. |

## Red Flags - STOP and Start Over

- "I don't have persistent storage between conversations"
- "If you'd like to make this permanent, you could add it to a global AGENTS.md"
- "I'll remember that for this session"

**All of these mean: Stop. Use the `memory.write` tool instead.**