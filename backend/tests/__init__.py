"""Configure a disposable database before importing any application modules."""
import os
import tempfile
from pathlib import Path

_test_database_dir = tempfile.TemporaryDirectory(prefix="sage-tests-")
os.environ["SAGE_DATABASE_URL"] = f"sqlite:///{Path(_test_database_dir.name) / 'test.db'}"
