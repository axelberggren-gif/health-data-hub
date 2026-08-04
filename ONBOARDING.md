# Working with this repo (a plain-language guide)

This project is set up to be **AI-first with guardrails**: AI agents write the code, automated
checks catch mistakes, and **you press the final Merge button**. You don't need to be technical
to run it. This page explains the few things you'll actually do.

## The big picture

- Nothing reaches the live code (`main`) without going through a **pull request (PR)**.
- Every PR runs **three automatic checks**. All three must be green before you can merge.
- One of those checks is an **AI reviewer** that reads the change against this project's rules
  (in `AGENTS.md`) and **blocks** anything risky.
- When the checks are green, **you click "Merge"**. That's the only manual step.

## The three checks (what each green check means)

On the PR page each check is listed by its **job** name, with the workflow name beside it:

| Check (job name) | From workflow | What it proves | If it's red (failed) |
|------------------|---------------|----------------|----------------------|
| **build** | `ci` | The code is formatted, type-correct, and the tests pass | Something is broken in the code — the AI should fix it and push again |
| **review** | `claude-review` | The AI reviewer found no bugs, no leaked secrets/data, and no broken project rules | Open the PR's "Files changed" / review comments to see what it flagged |
| **lint** | `pr-title-lint` | The PR title is in the required format (e.g. `feat: add oura source`) | Edit the PR title to start with a type like `feat:` or `fix:` |

## Your normal flow

1. Ask the AI (in Claude Code) to do something. It creates a branch and opens a PR.
2. Wait a minute or two for the checks to run (you'll see spinners, then ✓ or ✗ on the PR page).
3. **All green?** Click the green **Merge** button (choose "Squash and merge"). Done.
4. **Something red?** See below.

## How to read a "blocked" PR

On the PR page, scroll to the checks box near the bottom:
- A red ✗ next to **claude-review** → click **"Details"**, then read the review summary and the
  inline comments. They're written in plain language and say what to change.
- A red ✗ next to **ci** → the code itself is broken. Tell the AI "CI is failing, please fix it"
  — it can read the same logs and push a fix to the same PR. The checks re-run automatically.
- A red ✗ next to **pr-title-lint** → just edit the PR title (pencil icon) to start with
  `feat:`, `fix:`, `docs:`, `chore:`, etc.

## When the AI reviewer requests changes

Just tell the AI: *"The reviewer requested changes on this PR, please address the comments."* It
will read the comments, push new commits to the same branch, and the reviewer re-runs on its own.
You don't merge until it turns green.

## Dependency-update PRs (from "dependabot") — `review` is always red

Once a week, a bot called **Dependabot** opens PRs that bump a library to a newer version. On
those PRs the **`review` check will always be red**, and that is not a bug you or the AI can fix:
GitHub deliberately gives bot-opened PRs a read-only token and no access to secrets, so the AI
reviewer cannot run on them at all. `build` and `lint` still run normally.

What to do with one:

1. Check that **`build` is green** — that's your real safety net here, since it proves the app
   still builds, type-checks, and passes its tests with the new version.
2. Skim the PR description. Dependabot links the library's release notes; look for anything about
   breaking changes.
3. If it looks routine, merge it with the admin override (same button as below). If you'd rather
   not decide, leave it — an un-merged dependency bump is not urgent, and you can ask the AI to
   look at it in a session.

This is a deliberate trade-off, not an oversight: dependency updates are exactly where
supply-chain risk lives, so a human glance is the right default. (Recorded in ADR-0007.)

## Emergency: merging anyway (rare)

The rules are there to protect you, so this should almost never happen. But if a check is wrong or
stuck and you genuinely need to merge:

1. On the PR page, as the repo admin you'll see an option to merge despite failing requirements
   ("Merge without waiting for requirements to be met" / an admin override).
2. Use it only when you understand why the check is wrong.
3. Afterwards, ask the AI to add a short note in `docs/decisions/` explaining why — so there's a
   record.

## One-time setup you need to do (the parts I can't do for you)

1. **Give the AI reviewer its key.** The reviewer uses a pay-per-use **Anthropic API key** (the
   Claude Team plan can't mint a working Actions token — see ADR-0005). Create one at
   <https://console.anthropic.com> → **API keys → Create key** (add a payment method + a small
   monthly cap), then run:
   `gh secret set ANTHROPIC_API_KEY --repo axelberggren-gif/health-data-hub`
   and paste the key when prompted.
2. **Install the Claude GitHub App** on the repo: https://github.com/apps/claude → Install → pick
   this repo. This lets the reviewer post its review.
3. **Turn on 2FA** for your GitHub account (Settings → Password and authentication). You're the
   admin of a public repo wired to your Claude token — protect the account.
4. **Rotate your secrets once** as a precaution: re-issue the WHOOP **Client Secret** in the WHOOP
   developer dashboard and change your **Mill** password, then update your local `.env`. (Your
   `.env` was never committed, but rotating once removes any doubt.)

## If the AI reviewer suddenly stops working

The symptom: `claude-review` starts failing and PRs won't go green. Usual causes: the
`ANTHROPIC_API_KEY` was revoked or the Anthropic API budget ran out. The fix: check
<https://console.anthropic.com> (keys + billing), then re-set the secret with
`gh secret set ANTHROPIC_API_KEY --repo axelberggren-gif/health-data-hub`.

## Where the rules live

- `AGENTS.md` — the rules the AI follows and the reviewer enforces.
- `docs/decisions/` — why things are the way they are (decisions recorded over time).
- `SECURITY.md` — the security model and how to report a problem.
