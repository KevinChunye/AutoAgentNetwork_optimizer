# One image for every agent. Which agent a container plays comes from the
# request (AgentRequest JSON) or from AAN_NETWORK + AAN_AGENT_ID.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY autoagentnet ./autoagentnet
RUN pip install --no-cache-dir ".[anthropic,openai,serve]"
COPY configs ./configs
COPY start.py ./

ENV PYTHONUNBUFFERED=1
# Persistent state, if an agent ever needs it, belongs in /data (Maritime keeps it).
CMD ["python", "start.py"]
