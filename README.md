# sales-agents

A CLI that chains the "Art of Selling" agent-workshop prompts into one
pipeline: each stage's output automatically feeds the next stage's input,
the way the workshop's manual copy-paste was meant to work.

It asks you three things and nothing else:

```
  ▌ You sell for      the company whose product you are selling
  ▌ What they sell    one line on the product and who buys it
  ▌ Target account    the company you want to sell into
```

Those three answers are the only case-specific input. Nothing is hardcoded
to a product: the industry is worked out from the target account, and no
prompt file contains a company name.

```
icp -> shift -> account -> roles -> people -> pack -> grade research
     -> emails (style a and/or b) -> linkedin -> grade messages
```

Each stage calls the local `claude` CLI in headless mode, using your
existing Claude Code login, so there is no separate API key. Research
stages can use `WebSearch` and `WebFetch` and nothing else.

## Requirements

- Claude Code installed and logged in (`claude` on your `PATH`).
- Python 3.9+. Standard library only, no packages to install.

## Usage

```bash
./bin/sales-agents
```

That is the whole thing. It offers the six workshop pairings as a
shortcut, asks for anything it still needs, and runs. Your answers to
"You sell for" and "What they sell" are remembered as defaults for next
time; the target account never is.

Skip the questions by passing them:

```bash
./bin/sales-agents run \
  --seller "MoveInSync" \
  --sells "employee commute and fleet software" \
  --company "Tata Steel"
```

Resume an interrupted or paused run, and see what is on disk:

```bash
./bin/sales-agents continue research-chain/outputs/tata-steel
./bin/sales-agents list
```

## What you see while it runs

A live frame, repainted in place, showing every stage, the one that is
running, and what the model is doing inside it right now:

```
  ▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱▱▱▱  4/10 stages · 3m 12s · $0.41 · 9 searches · 4 pages

  ✔  0  The ICP — who should you sell to?            41.2s  4 verified · 1 asserted
  ✔  1  The shift — what changed in their industry?  1m 06s  3 verified · 2 asserted
  ✔  2  The account — where you would fit            1m 22s  5 verified · 0 asserted
  ⠹  3  The role — who would be involved             18.4s
  ○  4  The person — real names and evidence

      │ ◆ thinking · 2.4k tokens
      │ 🔎 WebSearch  Tata Steel head of administration  ← 12.1k chars
      │ 🌐 WebFetch   tatasteel.com/careers/life-at-tata  ← 8.4k chars
      │ ✎ writing answer · 3.1k chars
```

Completed stages leave a permanent line in the scrollback with their
duration, cost and output file. Piped output or `--plain` drops the
animation and narrates the same events as flat lines, so logs stay
readable.

## Reviewing between stages

By default the run pauses after each stage and shows a preview:

```
  [enter] continue   [e] edit   [r] retry   [a] run the rest   [q] quit
```

`[e]` opens `$EDITOR` on the file, so you can cut a bad claim before it
feeds the next stage. This is the point of the pause: automation moves you
from writing the research to deciding what is allowed to pass. Use
`--auto` to run straight through.

## The counts

Every stage ends with the workshop's machine-readable counters, and the CLI
reads them back. They appear next to each finished stage and again at the
end, with the workshop's own thresholds applied:

```
  Counts

  The shift — what changed …    VERIFIED: 3 | ASSERTED: 1 | TOTAL: 4
  Grade the research            ROWS: 12 | FAILED A: 2 | FAILED B: 1 | FAILED C: 3
                                Strong. Check it is useful, not just cautious.
  Grade the messages            SENTENCES: 20 | FROM PACK: 15 | GENERIC: 3 | MADE UP: 1
                                Does not go out: 1 made up, 0 banned.
```

- Under 50% of rows sourced: not usable in front of a buyer.
- 50–74%: normal first attempt, fix the prompt rather than the chat.
- 75%+: strong.
- Any `MADE UP` or `BANNED` sentence: the message does not go out.

## What is automated, and what is not

- **The pack** is its own stage: it extracts fields verbatim from stages
  0–4 into the fixed template, and is told to invent nothing.
- **The research grader** runs against the assembled pack and appends any
  row that fails source-check A to the pack's `## Do not use` section,
  before any email is written from it. Every later stage is forbidden from
  using those rows, reworded or not.
- **The message grader** labels every sentence `FROM PACK` / `GENERIC` /
  `MADE UP` / `BANNED`.
- **Choosing which buying signal carries forward** is not automated. The
  whole stage-0 output feeds stage 1; if you want to narrow it, use `[e]`
  at the checkpoint.

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--style {a,b,both}` | `a` | Which email style to write (A opens with the industry change, B opens with what the person said or did). |
| `--model` | `sonnet` | Model alias passed to `claude --model`. |
| `--auto` | off | Do not pause between stages. |
| `--budget` | none | Stop a stage that would cost more than this many dollars. |
| `--timeout` | `1800` | Seconds allowed per stage. |
| `--industry` | auto | Name the industry instead of letting stage 1 work it out. |
| `--group` | `""` | Workshop group label stamped on the pack. |
| `--plain` | auto | No colour, no animation. On by default when output is not a terminal. |
| `--out-dir` | `research-chain/outputs` | Where run folders live. |

## How the stages are run

Each stage is a fresh `claude -p` process with no memory of the last one,
which is deliberate: a grader that shares the writer's context shares the
writer's blind spots. Runs are isolated from local customisation
(`--safe-mode`, `--strict-mcp-config`, `--no-session-persistence`) so the
same inputs behave the same way on any machine, and restricted to
`WebSearch` and `WebFetch` so a stage can never edit a file or run a
command.

State lives in `research-chain/outputs/<account>/state.json`, so an
interrupted run resumes exactly where it stopped.

## Editing the prompts

Stage prompts live in `sales_agents/prompts/`. Keep them free of company
and product names: everything case-specific arrives through the three
inputs. A product name left inside a prompt file does not raise an error,
it just quietly keeps researching the wrong thing.

`sales_agents/context/our_product.md` is a fallback used only when no
"What they sell" answer is given.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
