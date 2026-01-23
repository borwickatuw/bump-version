# Architecture Decisions

This document records significant design decisions made during development.

## 001: Keep simple text-based prompts instead of arrow-key selection

**Date:** 2026-01-23

**Status:** Accepted

**Context:**

The CLI has several interactive prompts:
- Yes/No confirmations (sync repo, create tag, push tag)
- Bump type selection (major/minor/patch)
- Tag message options (use default, edit summary, edit in $EDITOR)

We considered whether to add arrow-key based selection using a library like `questionary` or `simple-term-menu` for a more polished, modern feel.

**Decision:**

Keep the current text-based interface with Y/n prompts and numbered choices.

**Rationale:**

1. **Standard CLI conventions** - Y/n and numbered menus are familiar patterns that users expect from command-line tools.

2. **Speed for power users** - Typing "y" + Enter is faster than navigating with arrow keys. Users who run this tool frequently benefit from quick keyboard input.

3. **No additional dependencies** - Avoiding external libraries keeps the tool simple to install and maintain.

4. **Terminal compatibility** - Text-based prompts work reliably in any terminal environment without edge cases.

5. **Appropriate complexity** - For a focused utility like bump-version, a simple interface is fitting. The tool does one thing well and doesn't need elaborate UI.

**Exceptions:**

We did enhance the summary editing prompt (option 2 in tag message selection) to use readline with pre-filled text. This allows standard terminal key bindings (Ctrl+A, Ctrl+E, etc.) when editing, which addresses a real usability pain point without adding dependencies.
