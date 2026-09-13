## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Live-mode guard (opencode)

`impeccable live` requires a foreground poll loop to service steer/generate events.
opencode has no background-task primitive, so a live session cannot stay alive
across tool calls and every invocation becomes a dead session. Do NOT chase "live
mode" as functional in opencode; it is not the end-state of the tool here.

To clean a live session, run `impeccable live-server stop` (idempotent; runs
`live-inject --remove`). The commit-time guard that previously scrubbed
`impeccable live` artifacts from the tracked Vite entrypoint
(`frontend/index.html`) was removed on this branch; do not re-add it.



## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
