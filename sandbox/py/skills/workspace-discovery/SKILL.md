---
name: workspace-discovery
description: Systematic vault exploration protocol for meta-file identification and discovery.
---

# Workspace Discovery Protocol

This skill defines the systematic protocol for exploring a workspace vault before acting on any task. The goal is to build a complete mental model of the workspace structure, policies, and available skills.

## Step-by-Step Exploration

### 1. Tree the Root

Start by running `tree("/")` to get the complete directory structure. This provides an overview of all top-level folders and files.

### 2. Read AGENTS.MD

Immediately read `AGENTS.MD` at the root (if present). This is the primary policy file that governs agent behavior. If it contains a redirect (e.g., "See README.MD"), follow the redirect and read the target file.

### 3. List All Top-Level Folders

For every top-level folder returned by the tree, run `list_dir()` on it. Do not skip folders that seem unrelated to the task -- any folder may contain meta-files or policies that affect your work.

### 4. Identify and Read Meta-Files

In every directory, look for files matching meta-file patterns (see references/meta-file-patterns.md for the complete list). Read all meta-files before reading data files. Meta-files include:

- `_rules.*` -- Directory-specific rules
- `RULES.*` -- Policy documents
- `skill-*.*` -- Vault-discovered skills
- `_config.*` -- Configuration files
- `_meta.*` -- Metadata documents
- `AGENTS.*` -- Agent policy files
- `README.*` -- Documentation and instructions
- `*.rules` -- Rule files with .rules extension

### 5. Explore Subfolders

For each subfolder discovered during listing, repeat the process: list its contents and read any meta-files found.

### 6. Read Skills Folder

If a `skills/` directory exists, read all files within it to understand available capabilities and vault-discovered skills.

## Key Principles

- **Exhaustive before selective**: Explore everything before deciding what matters.
- **Meta-files first**: Always read policy and rule files before data files.
- **Follow redirects**: If a file says "See X", read X immediately.
- **Track everything**: Every file read contributes to grounding references.
