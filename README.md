# sales-agents

A CLI that chains Prof. Rishabh Ladha's "Art of Selling" AI-agent-workshop
prompts (originally built around the Procol case) into one pipeline: each
step's output automatically feeds the next step's input, the way the
workshop's manual copy-paste was meant to work. Who you sell for, what you
sell, and the target account are all inputs — nothing is hardcoded to a
specific product.

```
icp -> industry -> account -> roles -> people -> pack -> grade_research
     -> emails (style a and/or b) -> linkedin -> grade_messages
```

Each stage calls the local `claude` CLI in headless mode (`claude -p`),
using your existing Claude Code login — no separate API key needed. Web
research stages are restricted to the `WebSearch` and `WebFetch` tools only.

## Requirements

- Claude Code installed and logged in (`claude` on your `PATH`).
- Python 3.9+ (stdlib only, no extra dependencies).

## Usage

```bash
./bin/sales-agents run --seller "MoveInSync" --company "Tata Steel" --industry "Steel manufacturing"
```

- `--seller` — who you sell for (e.g. "MoveInSync"). Used in the outreach
  copy ("Write three cold emails from a {{seller}} salesperson...").
- `--company` — the target account.
- `--industry` — the target account's industry.

This creates `research-chain/outputs/tata-steel/`, runs each stage in
order, and after every stage:

- writes the numbered output file (`00-icp.md`, `01-industry.md`, ...)
- shows a preview
- pauses for `[c]ontinue`, `[e]dit` (opens `$EDITOR` on the file so you can
  fix bad research before it feeds the next stage), `[r]etry`, or `[q]uit`

Pass `--auto` to run the whole chain unattended instead.

Resume a paused or interrupted run:

```bash
./bin/sales-agents continue research-chain/outputs/tata-steel
```

List runs and progress:

```bash
./bin/sales-agents list
```

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--style {a,b,both}` | `a` | Which cold-email style to generate (A: industry-change opener, B: opens with what the person said/did). |
| `--model` | `sonnet` | Model alias passed to `claude --model`. |
| `--group` | `""` | Workshop group label stamped on the pack. |
| `--out-dir` | `research-chain/outputs` | Where run folders live. |

## What's automated vs. manual

- **The "Put it all in one file" step** (the personalization pack) is its
  own AI stage: it extracts fields verbatim from steps 0-4 into the fixed
  template — it's told not to invent anything not already in the source
  text.
- **The research grader** (`grade_research`) runs against the assembled
  pack and automatically appends any row that fails source-check "A" into
  the pack's `## Do not use` section, before any emails are written from it.
- **The message grader** (`grade_messages`) runs after emails/LinkedIn are
  generated and labels every sentence `FROM PACK` / `GENERIC` / `MADE UP`
  / `BANNED`.

## Editing the product pitch

The "what we sell" one-liner used by every prompt (`{{our_product}}`) lives
in `sales_agents/context/our_product.md`. Edit it whenever you point this
chain at a different product — pair it with a matching `--seller` value on
the command line.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
