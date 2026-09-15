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
     -> emails -> linkedin -> grade messages
```

Each stage calls either the local `claude` CLI or `codex` CLI in headless mode,
using the selected tool's existing login, so there is no separate API key.
Claude remains the default. Use `--runner codex` to opt into Codex.

## Requirements

- Claude Code installed and logged in (`claude` on your `PATH`).
- Or Codex installed and logged in (`codex` on your `PATH`) when using
  `--runner codex`.
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

./bin/sales-agents run \
  --runner codex --model gpt-5.6-terra \
  --seller "Alfred Scholar" \
  --sells "a secure research workspace for researchers" \
  --company "IIT Hyderabad"
```

Resume an interrupted or paused run, see what is on disk, and write it
all to one page:

```bash
./bin/sales-agents continue research-chain/outputs/tata-steel
./bin/sales-agents list
./bin/sales-agents export
```

## Reading the outputs

```bash
./bin/sales-agents view
```

Pick a run from the list, then read every stage without leaving the
terminal. The stage list stays on the left, the stage's own output fills
the pane on the right, and the counters and verdict for whatever you are
looking at sit under the list:

```
  IIM Bangalore   Alfred Scholar → research workspace for scholars   2026-09-11

  ✔ The ICP — who should you sell …  │ Account: IIM Bangalore
  ✔ The shift — what changed in th…  │ What they do and where their money goes:
❯ ✔ The account — where you would …  │ Claim          IIMB runs a 5-year residential Doctoral
  ✔ The role — who would be involv…  │                Programme, fully funded via a ₹42,000/month
  ✔ The person — real names and ev…  │                stipend + tuition waiver
  ✔ The pack — everything in one f…  │ Source + date  IIMB PhD admission page, 2026 cycle
  ✔ Grade the research               │ Status         VERIFIED
  ✔ The emails — three, in sequence  │
  ✔ LinkedIn — connect request + 3…  │ Claim          IIMB owns and funds its own peer-reviewed
  ✔ Grade the messages               │                journal, IIMB Management Review
                                     │ Source + date  iimb.ac.in/imr (current site)
  02-account.md                      │ Status         VERIFIED
  VERIFIED: 10 | ASSERTED: 0 |       │
  TOTAL: 10                          │ How they handle this today:

  stage 3/10 · 1-28 of 121   ↑↓ scroll · ←→ stage · e edit · r runs · q quit
```

Markdown is rendered, not shown raw: headings stand out, `**markers**`
are gone, and a table lines up into columns. A table too wide for the
pane becomes labelled records, as above, because the alternative is
cutting off the source that makes the claim worth anything.

A tick means the stage ran; its colour, and `!`, are what the grader made
of what it produced. `VERIFIED` and `FROM PACK` are green, `ASSERTED`,
`INFERRED`, `GENERIC` and `STALE` amber, `MADE UP`, `BANNED` and
`DO NOT USE` red, so a weak stage is visible before you read a word of it.

| Key | Does |
| --- | --- |
| `↑` `↓` `j` `k` | Scroll the stage's text |
| `←` `→` `n` `p` `tab` | Previous / next stage |
| `pgup` `pgdn` `space` | Page through a long output |
| `home` `end` `g` | Jump to the top or bottom |
| `e` | Open the current stage in `$EDITOR` |
| `r` `esc` | Back to the list of runs |
| `q` | Quit |

Open one run directly with `./bin/sales-agents view <run-dir>`. Piped or
with `--plain`, it prints the same stage list and counters as flat text
instead of taking over the screen.

## Sending the runs to someone without the tool

```bash
./bin/sales-agents export
```

Writes `research-chain/outputs/report.html`: every run on one page, with
the stage list, each stage's output, its counters, and the verdicts. The
file is self-contained — no fonts, scripts or styles are fetched — so it
opens from disk, attaches to an email, and prints.

```
  ▰ 85.7%  of 7 graded rows name a source you could check
  ▰ 17/24  sentences in the emails trace back to a pack field
```

Each account opens with those two numbers, because they are what the
workshop marks. Under them the stages sit in a rail on the left and the
stage you picked fills the page, and the last section puts every run in
one table, so a run whose research went thin is obvious next to one whose
did not.

| Key | Does |
| --- | --- |
| `←` `→` | Previous / next stage |
| `shift` + `←` `→` | Previous / next account |
| `/` then `enter` | Search every stage, jump to the next one with a hit |
| `c` | Copy the stage you are reading |

```bash
./bin/sales-agents export --html report.html --open   # somewhere else, opened
./bin/sales-agents export research-chain/outputs/tata-steel   # one run only
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
  Grade the messages            SENTENCES: 24 | FROM PACK: 10 | INFERRED: 7 |
                                GENERIC: 7 | MADE UP: 0 | BANNED: 0
                                Strong. Read it aloud and check a person
                                could have written it.
```

- Under 50% of rows sourced: not usable in front of a buyer.
- 50–74%: normal first attempt, fix the prompt rather than the chat.
- 75%+: strong.
- Any `MADE UP` or `BANNED` sentence: the message does not go out.
- More `INFERRED` than `FROM PACK`: the email is reasoning where it
  should be citing. Go back for facts.

A sentence is `FROM PACK` when it says what a sourced field says, and
`INFERRED` when it only draws a consequence from pack fields without
adding a fact. The split matters because the email prompt asks for the
"so what" of a change: grading that as invention made the gate fire on
sentences it had itself demanded, which is how a real `MADE UP` gets
lost in the noise.

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
| `--runner` | `claude` | Runner to use: `claude` or `codex`. |
| `--model` | runner default | Model passed to the selected runner. |
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
