# Training records

Copied from the Colab output folder after the run that produced the shipped
model.

- `train.csv`, `val.csv`: the exact pairs the model was trained and validated
  on (columns: request, command, source dataset, tool).
- `data_manifest.json`: dataset revisions, how many pairs each filter removed,
  and a checksum of `train.csv`.
- `run_info.json`: settings and outcome of the training run.
- `log_history.csv`: training loss every 50 steps and validation loss every
  250.
- `versions.json`: package versions on the Colab machine.

Two things differ from the notebook as it is now. The run saved its files
under earlier names (`...-ft-r4` and `...-base-r4`, in a Drive folder called
`round4`), which is what `run_info.json` records; the notebook now writes
`...-finetuned` and `...-base-export`. And the base-model export failed once
during the run and was repeated with the model loaded in full precision, which
is what the notebook now does.
