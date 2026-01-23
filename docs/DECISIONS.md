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

## 002: Push only tags, not branches

**Date:** 2026-01-23

**Status:** Accepted

**Context:**

When a user chooses to push a tag (via `--push` or the interactive prompt), we need to decide what to push to the remote.

Options considered:
1. Push only the tag (`git push origin <tag>`)
2. Push the tag and the current branch (`git push origin <tag> && git push`)
3. Push the tag with `--follow-tags` after pushing the branch

**Decision:**

Push only the tag with `git push origin <tag>`.

**Rationale:**

1. **Minimal side effects** - The tool is for version tagging, not general git workflow management. Users may have reasons for not pushing their branch yet (pending review, CI checks, etc.).

2. **Commits are still pushed** - When you push a tag, Git automatically pushes the commit the tag points to (and its ancestors) if they don't exist on the remote. The commits are accessible via the tag.

3. **Predictable behavior** - Users know exactly what will happen: one tag gets pushed. No surprises about branch state.

4. **Easy to push branch separately** - If users want to update their branch on the remote, `git push` is a simple follow-up command.

**Consequences:**

After pushing a tag, users may see "Your branch is ahead of origin/main by X commits" because the branch reference wasn't updated. This is documented in the README.
