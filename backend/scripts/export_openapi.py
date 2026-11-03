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
    app = create_app(Settings(database_url="sqlite://"))
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
