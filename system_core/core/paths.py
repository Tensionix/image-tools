from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _real(path: Path) -> str:
    """The folder a path really leads to - links and junctions followed - in one case."""
    return os.path.normcase(os.path.realpath(str(path)))


def _within(inner: str, outer: str) -> bool:
    return inner == outer or inner.startswith(outer.rstrip("\\/") + os.sep)


def routes_cross(source: Path, target: Path) -> str:
    """Why the Target may not take what the Source holds; "" - it may.

    A copy is written into the Target under the path it has in the Source. A Target that is the
    folder of the Source, lies inside it or holds it makes the copies of one run the originals of
    the same run, or a copy lands on an original of its own: an original is replaced and the run
    says "done". Compared are the folders the paths really lead to - a junction in a parent folder
    makes two different strings one folder."""
    if source.is_file():
        if _real(source.parent) == _real(target):
            return "the Target is the folder of the Source itself: the copy would take its place. Choose another Target."
        return ""
    src, dst = _real(source), _real(target)
    if src == dst:
        return "the Target is the Source itself: the copies would take the place of the originals. Choose another Target."
    if _within(dst, src):
        return "the Target lies inside the Source: its files would be read as originals and copies could land on them. Choose a Target outside the Source."
    if _within(src, dst):
        return "the Source lies inside the Target: copies could land on the originals. Choose a Target that does not hold the Source."
    return ""


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    input: Path
    output: Path
    logs: Path
    report: Path
    workspace: Path
    config: Path
    system_core: Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for parent in [current, *current.parents]:
        if (parent / "system_core").exists() and (parent / "config").exists():
            return parent

    return Path(__file__).resolve().parents[2]


def get_project_paths(root: Path | None = None) -> ProjectPaths:
    project_root = (root or find_project_root()).resolve()
    return ProjectPaths(
        root=project_root,
        input=project_root / "input",
        output=project_root / "output",
        logs=project_root / "logs",
        report=project_root / "report",
        workspace=project_root / "workspace",
        config=project_root / "config",
        system_core=project_root / "system_core",
    )


def ensure_project_dirs(paths: ProjectPaths) -> None:
    for directory in [paths.input, paths.output, paths.logs, paths.report, paths.workspace, paths.config]:
        directory.mkdir(parents=True, exist_ok=True)

