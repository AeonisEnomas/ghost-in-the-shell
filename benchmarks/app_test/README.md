# App test

A test set of the requests Ghost in the Shell is built for: short, everyday
tasks typed by someone standing in a folder. It complements the NL2SH-ALFA
benchmark in `../model_selection`, which is public and independent but is
written as long specifications with explicit paths.

| | App test | NL2SH-ALFA test |
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
- `app_test.py`: runs commands in a bubblewrap sandbox and scores them.

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

- **Frozen on 2026-11-12, before any round 4 output was seen.** The requests
  must not be edited in response to a model's answers. If a reference turns
  out to be wrong, fix it, say so below, and re-score every model.
- **Not taken from training data.** The requests were written by hand for
  this test. `app_test.py overlap` checks them against a training file; at
  freeze time none of the 169 was an exact or near match of a round 4
  training request.
- **Validated.** `app_test.py check` confirms that every reference runs
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
uv run python app_test.py check
uv run python app_test.py generate NAME ../../models/MODEL.gguf
uv run python app_test.py score results/preds/*.jsonl
uv run python app_test.py overlap ../../training/round4/outputs/train.csv
```

`generate` uses the same system prompt, decoding settings and llama.cpp server
as the model-selection benchmark. `score` writes `results/report.md` and marks
each answer in `results/scored/`.
