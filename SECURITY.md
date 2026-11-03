# Security policy

## Reporting a vulnerability

Please do not publish credentials, proprietary STL files, or reproducible
exploit details in a public issue. Contact the repository owner privately
through the GitHub profile instead. Include the affected version and a minimal
description that does not contain customer geometry.

## Data and credentials

- Never commit API keys, Codex session files, task logs, or CAD/scan files.
- API keys configured in the desktop application are protected with Windows
  DPAPI for the current Windows user.
- Codex authentication is managed by the locally installed official Codex
  runtime. This repository does not contain or distribute login credentials.
- A Codex reconstruction may transmit prompts and model-derived information to
  OpenAI. Only process files you are authorized to disclose under the terms of
  the selected service.
- Generated CAD must be reviewed by a qualified engineer before manufacturing.

