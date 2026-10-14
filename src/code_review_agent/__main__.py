"""`python -m code_review_agent` runs the command line, the same as the `review-agent` command."""

from .app.cli import main

raise SystemExit(main())
