from __future__ import annotations

import uvicorn

from api.app import app


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8110, reload=True)
