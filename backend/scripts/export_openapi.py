"""Write the API's OpenAPI document to a file (used to generate the typed TS client)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    """Export the schema to the path given as the first argument."""
    out = Path(sys.argv[1])
    # Ignore the developer's .env so the schema is identical on every machine and in CI.
    settings = Settings(app_name="I-ITSM", database_url="sqlite://", _env_file=None)
    document = json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"
    out.write_text(document, encoding="utf-8", newline="\n")  # LF on Windows too


if __name__ == "__main__":
    main()
