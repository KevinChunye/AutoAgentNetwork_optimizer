#!/usr/bin/env bash
# Run one command in the quantization environment (llm-compressor), e.g. inside `step` (which needs an executable).
source "${QUANT_ENV:-$HOME/.venvs/aan-quant}/bin/activate" && exec "$@"
