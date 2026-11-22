# Model tests

Two tests of the model that writes commands, each comparing the fine-tuned
model with its base. Results and what they mean are in `../docs/finetuning.md`.

| Folder | Test set | Run |
|---|---|---|
| `app_requests/` | 169 short requests of the kind the app is built for, in a fixed sample folder | `uv run python run.py` |
| `nl2sh_alfa/` | The 300-prompt test split of the public NL2SH-ALFA benchmark, on its five test filesystems | `uv run python run.py` |

`common.py` holds what both share: the list of models, the llama.cpp server
and prompt, the sandbox settings and the McNemar test.

Each `run.py` asks every model for a command per request (reusing answers
saved in `results/answers/`), runs the commands in a bubblewrap sandbox, and
writes `results/report.md` and one file of marked answers per model in
`results/scored/`. Both need `llama-server` and `bwrap` installed and the
three model files in `../models/` (see the main README).

The tests of the app itself (pipeline, safety rules, sandbox, interface) are
in `../tests/`.
