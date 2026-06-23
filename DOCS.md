# Documentation index

A routing map from each document to the part of the project it is the source of
truth for. Before completing a change, find the row(s) whose subject your change
touched and update those documents **in the same change** — stale docs are defects.
When you add or remove a document, update this index too.

| Document | Source of truth for |
|---|---|
| [README.md](README.md) | Public-facing overview: architecture summary, project structure, quick-start usage, Obsidian vault schema, lens library contract |
| [INSTALL.md](INSTALL.md) | macOS deployment: Python dependency install, secrets setup, launchd bootstrap/bootout commands, dry-run and manual-run procedures, Obsidian vault setup, feed tuning |
| [design-spec.md](design-spec.md) | Observation note schema + frontmatter contract, adapter interface spec, instance config format and all valid keys, Obsidian vault folder structure + Dataview queries, processing prompt design, key architecture decisions and rationale |
