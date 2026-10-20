"""python -m eval                  score the labeled fixture suite
python -m eval run SOW SCOPE SESSION [SCANS_DIR]
                                score one saved agent run, with no gold scope
"""
import json
import sys
from pathlib import Path

from eval.score import format_report, run_suite, score_run


def _run_files(argv):
    if len(argv) not in (5, 6):
        print("usage: python -m eval [run SOW SCOPE SESSION [SCANS_DIR]]", file=sys.stderr)
        return 2
    sow = Path(argv[2]).read_text()
    scope = json.loads(Path(argv[3]).read_text())
    session = json.loads(Path(argv[4]).read_text())
    scans = None
    if len(argv) == 6:
        scans = {p.name: p.read_text() for p in Path(argv[5]).iterdir() if p.is_file()}
    report = score_run(sow, scope, session, scans)
    print(f"score {report['score']:.2f}  {'PASS' if report['passed'] else 'FAIL'}")
    for problem in report["problems"]:
        print(f"  {problem}")
    return 0 if report["passed"] else 1


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) > 1:
        return _run_files(argv)
    report = run_suite()
    print(format_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
