# Feynly

A terminal study system built on the Feynman technique: you don't understand
something until you can explain it simply in your own words. You pick a
concept, explain it in plain text, and it grades your explanation against
your own notes. It tells you what you got right, where you were vague, and
what you got wrong or left out.

Unlike a flashcard app that tests your *recall*, this grades your
*explanation*. That is a much harder and more honest test of real understanding.

Built for teaching many subjects: load any set of notes, and it schedules
what to review, tracks where you're weak, and flags where your notes
themselves are thin.

## What it does

- **Imports notes from photos.** Snap a whiteboard, textbook page, or
  handwritten sheet and it types them up for you
- **Grades your explanations** against your own notes, separating "vague"
  from "wrong" from "not in the notes at all"
- **Schedules reviews** with spaced repetition (SM-2), so concepts come
  back right before you'd forget them
- **Picks what to study next.** Due reviews first, then a weighted mix of
  weak spots, reinforcement, and unexplored concepts
- **Organizes by subject**, so you can scope a session to one of them
- **Tracks XP, levels, streaks and 12 badges**, all derived from your real
  history, so they apply retroactively and can never drift out of sync
- **Answers questions as a grounded tutor** that knows your notes and your
  scores, and flags out loud whenever it steps outside your notes
- **Flags gaps in your notes.** When you say something true that your
  notes don't cover, that's a note to improve rather than a mistake
- **Summarizes each session** to a markdown log you can review later
- **Runs in the browser too.** A full read/write interface sharing the same
  engine, so terminal and browser can never disagree
- **Reminds you daily** via a native macOS notification
- **Never loses your data.** Writes are atomic, and a corrupt file is
  quarantined rather than crashing the app or being overwritten

## Why it's free

- **Grading**: `claude -p` (headless Claude Code) via your Claude
  subscription, NOT the paid per-token API.
- **Interface**: your terminal, plus a local-only browser app.
- **Scheduling**: `launchd`, built into macOS.
- **Storage**: plain JSON files, no database.

The only credential you need is a Claude Code token. Nothing costs
anything, nothing is exposed to the network, and no data leaves your
machine except the grading prompt itself.

## Setup

### 1. Authenticate Claude Code for headless use
```
claude setup-token
claude -p "say hello"     # must print a reply before continuing
```
Put the token in `.env` as `CLAUDE_CODE_OAUTH_TOKEN`.

### 2. Install and load your notes
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the token above
python src/load_notes.py sample_notes.md    # try the 3 sample concepts first
```
Load your real notes the same way:

```
python src/load_notes.py chemistry.md physics.md      # several files at once
python src/load_notes.py notes.md --subject biology   # tag a whole file
python src/load_notes.py notes.md --replace           # overwrite instead of merge
```

**Notes format.** `## Concept Name` starts a concept, and everything under
it is the source text you'll be graded against. `# Subject Name` groups
every concept beneath it, so one file can hold several subjects:

```markdown
# Chemistry

## Covalent Bonding
Atoms share electron pairs...

## Acids and Bases
A Brønsted acid is a proton donor...

# Physics

## Inertia
An object resists change in its state of motion...
```

A `--subject` flag applies to concepts appearing before any `#` heading.
Concepts with no subject at all are grouped as `uncategorized`.

Keep your own notes in `notes/`. That folder is gitignored, so your material
never gets committed if you fork or push this repo.

**A note on note quality:** the grading is only ever as good as your notes,
and it will tell you so. Feed it one-line definitions and it will correctly
mark most of a good answer as "not covered by your notes". That is the
signal to go write better notes. Rich, explanatory notes produce genuinely
useful grading.

### Notes from photos

Most people's notes are on paper, a whiteboard, or a textbook page rather
than in markdown. Photograph them instead:

```
python src/import_notes.py photo.jpg
python src/import_notes.py page1.jpg page2.jpg --subject chemistry
python src/import_notes.py whiteboard.png --load     # skip the review step
```

It reads the image with `claude -p`'s vision, using your subscription. No API
key and no OCR service. The markdown lands in `notes/`. Handles
png, jpg, webp, heic and pdf. Several pages of one subject merge into a
single file.

Most terminals let you **drag a photo into the window to paste its path**,
so you rarely have to type one.

By default it writes the file and *stops* rather than loading it, because
the transcription becomes the answer key every future explanation is graded
against, so a misread word would quietly become a permanent grading error.
Read it over, fix anything wrong, then `load_notes.py` it. Pass `--load` to
skip that if you're confident.

It also refuses output with no `## Concept` headings, so photographing
something that isn't notes fails loudly instead of loading garbage.

### 3. Study
```
python src/study.py
```

## Using it

### Interactive

`python src/study.py`, then type a concept name, or `/next` to let it
choose for you. Type your explanation, finish with a blank line:

```
> /next
╭─ Next up ──────────────────────╮
│ photosynthesis                 │
│ due for review                 │
╰────────────────────────────────╯

  Plants take in CO2 and water, and use chlorophyll to capture sunlight...

╭──── photosynthesis, 8/10 ──────────────────────────────╮
│ The mechanism is accurate and well-sequenced...          │
│                                                          │
│ Correct                                                  │
│   • Light reactions occur in the thylakoid membranes     │
│ Vague                                                    │
│   • Never states the overall energy-conversion purpose   │
│ Wrong / missing                                          │
│   • Restricts it to plants, notes include algae too     │
│                                                          │
│ Next review: 2026-08-19                                  │
╰──────────────────────────────────────────────────────────╯
```

Commands: `/next`, `/review`, `/due`, `/list`, `/subjects`, `/focus`,
`/history <concept>`, `/progress`, `/ask <question>`, `/tutor`, `/weak`,
`/stats`, `/help`, `/exit`.
`/cancel` backs out mid-explanation. On exit you get a session summary and
a saved log.

**`/review` is the daily workflow.** It drills straight through every
concept that's due, one after another, and summarizes at the end.

**Focusing on one subject.** `/focus chemistry` scopes `/next`, `/due`,
`/list`, `/weak`, and `/stats` to that subject for the rest of the session;
`/focus` alone clears it. Or start focused:

```
python src/study.py --subject chemistry
```

### One-shot / scriptable

```
python src/study.py list                 # all loaded concepts, with subjects
python src/study.py subjects             # subjects and their coverage
python src/study.py due                  # what's due for review
python src/study.py next                 # what to study now, and why
python src/study.py review               # drill through everything due
python src/study.py weak                 # your lowest averages
python src/study.py stats                # coverage and overall average
python src/study.py history inflation    # every attempt at one concept
python src/study.py progress             # XP, level, streaks and badges
python src/study.py tutor "why am I weak at inflation?"
python src/study.py tutor                # back-and-forth tutor chat
python src/study.py tutor --forget       # clear the tutor's memory
echo "my explanation" | python src/study.py explain inflation
```

Most commands take `--subject S` to scope them; `weak` also takes
`--limit N`. These exit with real status codes (0 ok, 1 failure, 2 usage
error), so they compose in shell scripts and cron jobs. `--help` works on
the top level and on every subcommand.

### Browser interface

```
python src/webapp.py               # then open http://127.0.0.1:5050
python src/webapp.py --port 8080   # if that port is taken
```

A full read/write interface rather than just a dashboard. Explain concepts
and get graded, drag in photos of notes, ask the tutor, see your progress.

| Page | What it does |
|---|---|
| **Study** | picks a concept, takes your explanation, shows colour-coded feedback |
| **Progress** | level, XP, streaks, badges, per-subject coverage, every concept |
| **Tutor** | grounded chat with persistent memory |
| **Notes** | drag-and-drop photo upload, with a review step before saving |

It adds no study logic of its own. Every route delegates to the same modules
the terminal calls, so the two front ends can never disagree about a score or
a schedule. There's a test asserting exactly that.

**It binds to localhost only.** `--host 0.0.0.0` exposes it to your
network, which is unauthenticated by design and lets anyone who reaches it
spend your Claude subscription, so it warns loudly when you do.

(Port 5050 rather than 5000 because macOS AirPlay Receiver occupies 5000
and makes a server there fail confusingly.)

### Daily reminders (macOS)

```
./scheduling/install_reminder.sh          # daily at 19:00
./scheduling/install_reminder.sh 9 30     # daily at 09:30
./scheduling/install_reminder.sh --uninstall
```

Installs a `launchd` agent that posts a notification naming what's due. It
stays silent when you're caught up. A reminder that fires when there's
nothing to do just teaches you to ignore reminders.

## How the scheduling works

Scores map onto SM-2's quality scale, where a 10 point score halves into
SM-2's 0 to 5. Score 6 or above counts as a pass and pushes the next review
further out: 1 day, then 6 days, then multiplied by an ease factor. Score 5
or below is a lapse. The interval resets to 1 day and the ease drops, so a
concept you keep fumbling keeps coming back.

`next` honors due reviews above everything else. Only when nothing is due
does it fall back to a weighted mix: 60% weak concepts, 30% reinforcing
strong ones, 10% something you've never tried.

## The tutor

Grading is one-directional. You explain, it judges. The tutor is the other
half: you ask, it answers.

```
python src/study.py tutor "what did I keep missing on photosynthesis?"
python src/study.py tutor                # open a back-and-forth chat
```

It sees your notes and your score history, so it answers specifically
("photosynthesis and supervised learning, both at 6.5/10") rather than
generically. Conversation memory persists across runs; `--forget` clears it.

**It is grounded on purpose.** The same discipline that makes the grading
trustworthy applies here: it answers from *your* notes, and when it steps
outside them it has to say so:

> *"(Your notes don't cover study technique, so from general knowledge: ...)"*

If your notes contradict what it believes, it says that too, rather than
silently overriding your material. An ungrounded study chatbot will happily
teach you things your source doesn't support and you'd never notice; this
one makes the boundary visible.

## XP, levels and badges

`study.py progress` shows your level, XP, streaks, and which of the 12
badges you've earned: Perfectionist (a 10/10), Comeback (recovering from
4/10 or below by 4+ points), Deep Diver, Explorer, Scholar, Century, three
streak badges, Subject Master (8+ across *every* concept in a subject), and
Polymath.

All of it is **derived from your attempt history, never stored separately**.
That means there's no second source of truth to corrupt or drift, badges
apply retroactively to study you did before the feature existed, and the
terminal and the dashboard can never disagree. There's a test asserting
exactly that.

XP is `5 + score × 10` per explanation, so a wrong answer still earns
something for showing up, and a great one earns much more.

## Your data

Everything lives in `data/` as plain JSON and markdown you can read, edit,
back up, or delete:

- `data/concepts.json` holds your loaded notes
- `data/progress.json` holds score history and the review schedule
- `data/sessions/*.md` is one markdown log per study session

Both JSON stores are written atomically (temp file + rename), so a crash or
a full disk can't leave you with a half-written file. If a file is ever
found corrupt anyway, it's moved aside as `*.corrupt-<timestamp>` and the
app starts clean instead of crashing or overwriting it, so your data is
always recoverable by hand.

Grading failures are retried automatically (they're usually a timeout or
the model returning prose instead of JSON). If every retry fails, your
explanation is written to `data/unsent/` rather than lost, so a long answer
never disappears because of a hiccup.

Store formats have changed twice as features landed; both migrations run
automatically on load, so older files keep working.

## Running the tests

```
pytest
```
356 tests cover the concept store and its subject grouping, spaced-repetition
scheduling, XP/levels/streaks/badges, progress tracking, both store migrations,
atomic writes and corruption recovery, grader retries and explanation
preservation, session summaries, the review drill, per-concept history, the
CLI's argument parsing and interactive loop, subject scoping, the web
dashboard, and the reminder. All of it runs with
all with the `claude -p` call mocked, so the suite runs in well under a
second with no network use and no draw on your subscription. The grading
pipeline was verified end-to-end against real `claude -p` calls during
development.

CI runs the suite on Python 3.10 to 3.13 on every push.

## Files

| File | Purpose |
|---|---|
| `src/study.py` | the terminal app, and what you actually run |
| `src/scheduler.py` | SM-2 spaced repetition + adaptive concept selection |
| `src/progress.py` | score history and review state |
| `src/grader.py` | grades an explanation via `claude -p` |
| `src/concepts.py` | loads/searches your notes, groups them by subject |
| `src/storage.py` | atomic JSON writes and corruption recovery |
| `src/gamification.py` | XP, levels, streaks and badges (all derived) |
| `src/tutor.py` | grounded tutor chat with persistent memory |
| `src/session.py` | session recording and markdown summaries |
| `src/conversation.py` | transport-agnostic conversation engine |
| `src/load_notes.py` | notes loader |
| `src/import_notes.py` | turns photos of notes into markdown via claude vision |
| `src/webapp.py` | browser interface (study, progress, tutor, notes) |
| `src/templates/`, `src/static/` | the web UI |
| `scheduling/remind.py` | macOS notification about what's due |
| `scheduling/install_reminder.sh` | installs/removes the launchd agent |
| `tests/` | 356 tests |

## What makes this worth building (and not generic)

Most study tools quiz you: question in, did-you-remember out. This
inverts it: you produce the explanation, and the grading is grounded
strictly in your own source, so it distinguishes "you're vague here" from
"you're wrong here" from "the notes don't cover that." That grounding
discipline, separating unsupported from contradicted, is the same
principle behind a good RAG eval, applied to teaching yourself.

The notes-gap detection falls out of that discipline for free, and is the
part that matters most if you teach: it tells you where *your material* is
thin, not just where your understanding is.

`conversation.py` and `scheduler.py` deliberately know nothing about the
terminal. Adding another front end means writing an adapter, not touching
the grading or scheduling logic.
