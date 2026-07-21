from __future__ import annotations

import os
import threading

from dotenv import load_dotenv

load_dotenv()

from bot.client import VertexBot
from web.app import create_app


def run_web() -> None:
    app = create_app()
    port = int(os.environ.get("PORT", 8081))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN fehlt (.env oder Render Environment Variable setzen).")

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    bot = VertexBot()
    bot.run(token)


if __name__ == "__main__":
    main()
