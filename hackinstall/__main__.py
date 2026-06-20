"""Allow ``python -m hackinstall`` to run the CLI."""
from .main import main

raise SystemExit(main())
