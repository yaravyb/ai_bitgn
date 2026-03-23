# Meta-File Patterns

The following filename patterns identify meta-files that should be read before data files in any directory. All pattern matching is case-insensitive.

## Pattern List

| Pattern | Description | Examples |
|---------|-------------|----------|
| `_rules.*` | Directory-specific rules | `_rules.md`, `_rules.txt` |
| `RULES.*` | Policy documents | `RULES.md`, `RULES.txt` |
| `skill-*.*` | Vault-discovered skills | `skill-todo.md`, `skill-template.txt` |
| `_config.*` | Configuration files | `_config.yaml`, `_config.json` |
| `_meta.*` | Metadata documents | `_meta.md`, `_meta.json` |
| `AGENTS.*` | Agent policy files | `AGENTS.MD`, `AGENTS.md` |
| `README.*` | Documentation | `README.md`, `README.txt` |
| `*.rules` | Rule files by extension | `formatting.rules`, `naming.rules` |

## Regex Patterns

For programmatic detection, use these regex patterns with case-insensitive flag:

```
^_rules\..*$
^rules\..*$
^skill-.*\..*$
^_config\..*$
^_meta\..*$
^agents\..*$
^readme\..*$
.*\.rules$
```

## Priority

When multiple meta-files exist in the same directory:
1. Read `AGENTS.*` first (primary policy)
2. Read `_rules.*` and `RULES.*` (directory-specific rules)
3. Read `_config.*` and `_meta.*` (configuration and metadata)
4. Read `skill-*.*` (skills)
5. Read `README.*` (general documentation)
6. Read `*.rules` (additional rule files)
