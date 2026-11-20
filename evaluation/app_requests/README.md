# App requests

A test set of the requests Ghost in the Shell is built for: short, everyday
tasks typed by someone standing in a folder. It complements the NL2SH-ALFA
benchmark in `../nl2sh_alfa`, which is public and independent but is written
as long specifications with explicit paths.

| | App requests | NL2SH-ALFA test |
|---|---|---|
| Requests | 169 | 300 (275 scoreable) |
| Median length | 7 words | 10 words |
| Names an absolute path | 0% | 54% |
| Says "here", "this", "my" or "I" | 21% | 1% |
| Phrased as a question | 26% | 0% |
| Written by | this project | MIT researchers |

## What is in it

- `prompts.json`: 169 requests in 13 groups (list, find, search, count, size,
  view, text, create, move, delete, permissions, archive, other), each with one
  or more reference commands.
- `fixture.py`: the folder the requests are run in. A made-up home directory
  with a project folder: notes, logs, spreadsheets, Python files, photos,
  archives. File contents are fixed, and file ages are set relative to the
  moment the folder is built.
- `run.py`: asks the models, runs their commands in a bubblewrap sandbox and
  scores them.
- `results/`: each model's answers, the marked answers and the report.

## How a command is judged

Each command runs in a fresh copy of the folder, with the project folder as
the working directory, no network and a 10-second limit.

- If the reference command changes files, the prediction is correct when it
  leaves exactly the same files behind (path, type, permissions, content).
  What it prints is ignored, so `rm -v` and `rm` are the same answer.
  Archives are compared by what they contain, not byte for byte.
- If the reference only prints, the prediction is correct when it prints the
  same lines and changes nothing. Spacing, blank lines and a leading `./` are
  ignored. Line order is ignored too, except for requests about ordering
  (marked `"ordered": true`).

A request can have several references when the wording allows more than one
reading. "How many python files do I have here" accepts both the count for
this folder and the count including subfolders. 70 of the 169 requests accept
more than one result.

References are run again in every scoring session and never cached, so the
score does not depend on the day, on an earlier run, or on the machine's
state.

## Rules that keep it honest

- **Frozen on 2026-11-12, before any output of the fine-tuned model was seen.** The requests
  must not be edited in response to a model's answers. If a reference turns
  out to be wrong, fix it, say so below, and re-score every model.
- **Not taken from training data.** The requests were written by hand for
  this test. `run.py overlap` checks them against the fine-tuning data
  (`finetune/records/train.csv`): none of the 169 is an exact or near match
  of a training request.
- **Validated.** `run.py check` confirms that every reference runs
  without error, gives the same result twice, and is not matched by a command
  that does nothing.

## Limitations

- The requests were written by the project, not collected from users, so they
  reflect our idea of typical use. NL2SH-ALFA stays in the evaluation as the
  independent check.
- Requests whose answer depends on the machine (free disk space, running
  processes, the date) are left out, because they cannot be scored by
  execution.
- Commands run with the host's tools. A correct answer that uses a program
  this machine does not have (`zip`, `tree`, `bc`) is marked wrong; such
  requests were avoided where possible.
- With 169 requests, a difference between two models smaller than about 7
  points is within noise. Use the paired McNemar test that `score` prints.
- An unusual but valid output format that no reference covers is marked
  wrong. This affects all models alike.

## Usage

From this folder:

```
uv run python run.py            # ask every model, then score
uv run python run.py check      # validate the test set itself
uv run python run.py overlap    # requests too close to the fine-tuning data
```

The models are asked with the system prompt the app uses, greedy decoding and
a fixed seed. Answers saved in `results/answers/` are reused; delete a file to
ask that model again.
