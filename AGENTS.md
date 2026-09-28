# Instructions for future maintainers and coding agents

Read README.md and docs/maintenance.md before changing behavior.

## Preserve these contracts

- Seven feeds and their existing public paths must remain stable.
- All DC boards except dcbest use exception_mode=recommend. Exclude notices.
- Stable canonical article URLs are GUIDs. Do not change normalization casually:
  Feedly would treat existing articles as new.
- Keep each source's title emoji. Source IDs identify both saved state and files.
- Preserve last good XML and success metadata on collection/rendering failure.
- Publish healthy sources and failure status before marking Actions failed.
- No external heartbeat monitoring; do not claim stopped schedules are detected.
- Never commit the user's original feedly-opml-*.xml, credentials, .venv or site/.
- Never erase or force-push the data branch to fix a parser.

## Working practices

Use Python 3.12. Tests are offline and use unittest; run them before a commit.
Install requirements-dev.txt for Black, then run `black --check build.py rss_service tests`.
For parser repairs add a small sanitized HTML/XML fixture or regression test.
Live requests are opt-in (`python build.py --output /tmp/rss-check`); limit traffic.
Do not weaken validation merely to turn a failed run green.

Before push, inspect the diff and run the tests. After an authorized push, verify
Actions and the public status/RSS endpoints. Never claim email delivery has been
tested unless the user actually confirms it. Account notification settings are
outside the repository's control.
