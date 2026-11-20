# Kantine67 menu → Teams

A GitHub Actions job checks https://kantine67.at/#menue every hour. When the
Wochenmenü image changes, it crops off the poster header and footer, stores the
image in `menus/`, and posts it to a Teams channel through a Teams Workflows
webhook.

- Workflow: `.github/workflows/kantine-menu.yml`
- Script: `scripts/check_menu.py`
- Last posted menu: `state/last.json` (delete it to force a repost)
- Secret: `TEAMS_WEBHOOK_URL` (repo Settings → Secrets and variables → Actions)

The repo must be **public**, because Teams loads the image from
`raw.githubusercontent.com`.

Local test without git or posting: `DRY_RUN=1 python scripts/check_menu.py`
