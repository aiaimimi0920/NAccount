"""Include the deployment-owned suite in the repository's standard test command."""

from pathlib import Path


def load_tests(loader, tests, pattern):
    folder = Path(__file__).resolve().parents[1] / ".sba/tests"
    return loader.discover(str(folder), pattern="test_*.py", top_level_dir=str(folder))
