"""Run CI on a hosted desktop; fail if GUI tests are skipped."""
import os
from pathlib import Path
import sys
import unittest


root = Path(__file__).resolve().parents[2]
os.chdir(root)
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover("tests")
report = root / "test-results.txt"
with report.open("w", encoding="utf-8") as output:
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
print(report.read_text(encoding="utf-8"))
passed = result.wasSuccessful() and not result.skipped
summary = (
    f"## Person 4 tests: {'passed' if passed else 'failed'}\n\n"
    f"Tests: {result.testsRun}; failures: {len(result.failures)}; "
    f"errors: {len(result.errors)}; skipped: {len(result.skipped)}.\n\n"
    "All GUI tests must run. Download the person4-test-results artifact for details.\n"
)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write(summary)
if result.skipped:
    print("CI requires the Tkinter tests to run; skipped tests count as a failure.")
raise SystemExit(0 if passed else 1)
