# Contributing to openpodgo

Thanks for your interest! openpodgo is a community reverse-engineering project
for the Line 6 POD Go on Linux. Contributions of all kinds are welcome.

## Ground rules

- **English only** — code, comments, docstrings, commits and docs.
- **Never commit proprietary or personal data.** No Line 6 / POD Go Edit assets
  (images, fonts, manuals, `res/`), no device backups (`.pgb`), no raw USB
  captures (`.pcapng`), and no personal presets. `.gitignore` already excludes
  the usual suspects; keep it that way.
- Be respectful. This is a hobby project maintained on best effort.

## Development setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,ui]'
python -m pytest
```

The test suite is **fully offline** — it needs no pedal and no proprietary
resources. In a fresh clone it runs 315 tests; ~28 more are skipped because they
require the official POD Go Edit resources or your own captures locally (see the
skip guards in `tests/`).

If you have a POD Go, hardware validation is done manually with the scripts in
`tools/` and `scripts/`. Close the app first — only one process can claim the
USB vendor interface.

## Pull requests

- Keep changes focused; add or update tests where it makes sense.
- Make sure `python -m pytest` passes before opening the PR.
- For protocol/RE findings, update the relevant notes in `docs/`.

## Where help is most valuable

- Validation against POD Go firmware versions other than **v2.01**.
- Filling in reverse-engineering gaps flagged in `docs/specs/`.
- UI polish and bug fixes.

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
