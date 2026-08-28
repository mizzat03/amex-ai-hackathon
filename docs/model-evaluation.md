# Copilot model evaluation

Status: `PENDING_CREDENTIALS`  
Winner: none selected

The provider-neutral implementation, 14-case labelled regression set, fake-provider suite,
hard-gate validator, deterministic fallback, and blinded artifact generator are complete. No live
provider call was made because the required variables were not configured. A model winner must not
be inferred from fake-provider results or structural validation.

## Required environment-variable names

- `ANTHROPIC_API_KEY` — supplied through the operator's secret manager or process environment.
- `OPENAI_API_KEY` — supplied through the operator's secret manager or process environment.
- `AMEX_EVAL_CLAUDE_MODEL` — the provider-resolved Claude Sonnet 5 model ID.
- `AMEX_EVAL_TERRA_MODEL` — the provider-resolved GPT-5.6 Terra model ID.

Do not put credential values in `.env.example`, source, command history, issue text, chat, logs, or
commits. The evaluation command reads credentials only from the process environment and never
prints them.

## Locked evaluation command

After configuring the four variables in the execution environment:

```powershell
.\.venv\Scripts\python.exe scripts\run_copilot_evaluation.py --repetitions 3 --output docs\model-evaluation-results.json --mapping-output docs\model-evaluation-candidate-map.json
```

The command runs identical prompts, evidence, schema, tools, limits and balanced/medium reasoning
conditions for both candidates. It writes validated outputs for blind review and a separate
candidate map. Its result remains `AWAITING_BLIND_RUBRIC`; a human reviewer must apply the locked
100-point rubric and confirm all grounding, isolation, authorization and operational-safety hard
gates before recording a winner. Quality and worst-case reliability precede latency/cost.

After a winner is properly recorded, configure exactly one runtime provider/model for both modes:

- `AMEX_COPILOT_PROVIDER=anthropic` with `AMEX_COPILOT_MODEL` and `ANTHROPIC_API_KEY`; or
- `AMEX_COPILOT_PROVIDER=openai` with `AMEX_COPILOT_MODEL` and `OPENAI_API_KEY`.

Do not configure runtime provider switching or fallback to the losing provider. With
`AMEX_COPILOT_PROVIDER=disabled`, the product deliberately returns the labelled deterministic
fallback.
