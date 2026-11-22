"""Entry point. `python app.py` runs the development server; production
servers (gunicorn) use `app:app`. The application lives in fipconnect/."""

import os

from fipconnect import create_app
from fipconnect.config import ROOT, load_env_file

load_env_file(ROOT / ".env")
app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
