"""Отчёт pytest (JUnit XML) -> Markdown для страницы Summary в GitHub Actions.

Запуск:
    python .github/scripts/test_summary.py test-results.xml "Заголовок" >> "$GITHUB_STEP_SUMMARY"
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ICONS = {"passed": "✅", "failed": "❌", "error": "💥", "skipped": "⏭️"}


def outcome(case: ET.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def render(report: Path, title: str) -> str:
    if not report.exists():
        return f"## 💥 {title}\n\nОтчёт не найден: тесты не запустились (см. лог шага).\n"

    cases = list(ET.parse(report).getroot().iter("testcase"))
    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for case in cases:
        # classname "tests.test_api" -> "test_api.py"
        file = case.get("classname", "").rsplit(".", 1)[-1] + ".py"
        by_file[file].append((case.get("name", ""), outcome(case)))

    totals: dict[str, int] = defaultdict(int)
    for tests in by_file.values():
        for _, result in tests:
            totals[result] += 1
    duration = sum(float(c.get("time", 0)) for c in cases)
    ok = totals["failed"] == 0 and totals["error"] == 0

    lines = [
        f"## {'✅' if ok else '❌'} {title}",
        "",
        f"**{totals['passed']} passed** · {totals['failed']} failed · "
        f"{totals['error']} errors · {totals['skipped']} skipped · {duration:.2f}s",
        "",
        "| Файл | Тестов | Passed | Failed |",
        "|---|---:|---:|---:|",
    ]
    for file, tests in sorted(by_file.items()):
        passed = sum(r == "passed" for _, r in tests)
        failed = sum(r in ("failed", "error") for _, r in tests)
        icon = "✅" if failed == 0 else "❌"
        lines.append(f"| {icon} `{file}` | {len(tests)} | {passed} | {failed} |")

    # Упавшие тесты — сразу на виду, остальные — в раскрывающихся списках по файлам
    failed_tests = [
        (f, n) for f, tests in by_file.items() for n, r in tests if r in ("failed", "error")
    ]
    if failed_tests:
        lines += ["", "### Упавшие тесты", ""]
        lines += [f"- ❌ `{f}::{n}`" for f, n in failed_tests]

    lines += ["", "### Все тесты", ""]
    for file, tests in sorted(by_file.items()):
        lines += [f"<details><summary><code>{file}</code> — {len(tests)}</summary>", ""]
        lines += [f"- {ICONS[r]} `{n}`" for n, r in tests]
        lines += ["", "</details>", ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "test-results.xml")
    print(render(path, sys.argv[2] if len(sys.argv) > 2 else "Тесты"))
