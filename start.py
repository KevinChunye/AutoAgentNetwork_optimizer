"""Maritime entrypoint: serve one agent on 0.0.0.0:$PORT (Maritime injects PORT)."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "autoagentnet.serve.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
    )
