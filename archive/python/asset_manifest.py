"""Asset coverage for the PyInstaller build and the exe smoke test.

The game opens files from two asset folders: ``assets/fonts`` (UI fonts, listed in
``fonts.py``) and ``assets/audio`` (music loops listed in ``audio.py``, plus one
``sfx_<name>.wav`` per sound passed to ``AudioManager.play``). This module finds those
files by reading the sources with ``ast``, so nothing is imported and pyglet is never
loaded, and checks them against what ``kiro2_game.spec`` bundles.

Sound names come from the literal arguments of ``.play(...)`` calls, including both
branches of a conditional expression, the default of ``NAME_SFX.get(key, default)``, and
a module-level ``NAME = "literal"`` constant. Every string value of a module-level dict
whose name ends in ``_SFX`` counts too. A ``play`` argument that does not resolve to
literal names is an error, because the check could not tell which file it opens, unless
its file is listed in DYNAMIC_SOUND_TABLES.

Usage:
  python asset_manifest.py           print the coverage summary; exit 1 on any problem
  python asset_manifest.py --list    print every asset path the code opens, one per line

Used by kiro2_game.spec (the build fails when verify_bundle() raises) and by
tools/smoke_exe.ps1 (which checks the built _internal folder against --list).
"""

from __future__ import annotations

import argparse
import ast
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Folders the game reads at runtime. The spec bundles every file in each of them.
ASSET_FOLDERS = ("assets/fonts", "assets/audio")

_FONT_SOURCE = "fonts.py"
_FONT_CONSTANT = "_UI_FONT_FILES"
_AUDIO_SOURCE = "audio.py"
_MUSIC_CONSTANT = "_MUSIC_FILES"

# Folders that are not part of the game build.
_SKIP_DIRS = {"tools", "vercel_site", "build", "dist", "assets", "__pycache__"}

# A file whose play() takes a parameter, not a literal: its name argument only ever holds a key of the
# named module-level table, so the keys are the sounds it can open (each key still needs its WAV).
# audio_cues.cue(audio, name) plays names from CUE_SPECS; its keys are checked by the coverage test.
DYNAMIC_SOUND_TABLES = {"audio_cues.py": "CUE_SPECS"}


def _to_path(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/"))


def _read_module(path: str) -> ast.Module:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return ast.parse(fh.read(), filename=path)


def module_constant(path: str, name: str):
    """Literal value of the module-level assignment ``name = ...`` in ``path``."""
    for node in _read_module(path).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(value)
    raise ValueError(f"{path}: no module-level literal named {name}")


def _module_strings(tree: ast.Module) -> dict:
    """The module's own ``NAME = "literal"`` assignments, so ``play(NAME)`` resolves to its sound."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _table_keys(tree: ast.Module, table: str):
    """String keys of the module-level dict literal ``table``, or None when the module has no such table."""
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == table for t in targets):
                keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                return keys or None
    return None


def _sound_names(node: ast.AST, consts: dict | None = None):
    """Literal sound names ``node`` can evaluate to, or None when it cannot be resolved.

    ``consts`` holds the module's own string constants (see _module_strings).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name) and consts and node.id in consts:
        return {consts[node.id]}
    if isinstance(node, ast.IfExp):
        body = _sound_names(node.body, consts)
        orelse = _sound_names(node.orelse, consts)
        if body is None or orelse is None:
            return None
        return body | orelse
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id.endswith("_SFX")
        and len(node.args) == 2
        and not node.keywords
    ):
        # NAME_SFX.get(key, default): the table values are collected from the dict itself.
        return _sound_names(node.args[1], consts)
    return None


def _play_argument(node: ast.Call):
    """The sound-name expression of a ``.play(...)`` call, or None when it takes none."""
    if node.args:
        return node.args[0]
    for kw in node.keywords:
        if kw.arg == "name":
            return kw.value
    return None


def _code_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(".py") and not name.startswith("test_"):
                yield os.path.join(dirpath, name)


def scan_sound_names(root: str = PROJECT_ROOT):
    """Return ``(sound names, unresolved sites)`` for the game's Python sources.

    Unresolved sites are ``"path:line"`` strings for sound arguments that are not
    literal names, so the check cannot see which file they open.
    """
    names: set[str] = set()
    unresolved: list[str] = []

    def add(expr: ast.AST, rel: str, lineno: int, tree: ast.Module, consts: dict) -> None:
        found = _sound_names(expr, consts)
        if found is None and isinstance(expr, ast.Name) and rel in DYNAMIC_SOUND_TABLES:
            found = _table_keys(tree, DYNAMIC_SOUND_TABLES[rel])
        if found is None:
            unresolved.append(f"{rel}:{lineno}")
        else:
            names.update(found)

    for path in _code_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        tree = _read_module(path)
        consts = _module_strings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "play":
                arg = _play_argument(node)
                if arg is not None:  # pyglet player.play() takes no sound name
                    add(arg, rel, node.lineno, tree, consts)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id.endswith("_SFX") for t in targets):
                    for value in node.value.values:
                        add(value, rel, node.lineno, tree, consts)
    return names, unresolved


def referenced_assets(root: str = PROJECT_ROOT):
    """Return ``(sorted asset paths the code opens, unresolved sites)``.

    Paths are project-relative with forward slashes, for example
    ``assets/audio/sfx_hit.wav``.
    """
    refs: set[str] = set()
    for name in module_constant(_to_path(root, _FONT_SOURCE), _FONT_CONSTANT):
        refs.add(f"assets/fonts/{name}")
    for name in module_constant(_to_path(root, _AUDIO_SOURCE), _MUSIC_CONSTANT).values():
        refs.add(f"assets/audio/{name}")
    names, unresolved = scan_sound_names(root)
    for name in names:
        refs.add(f"assets/audio/sfx_{name}.wav")
    return sorted(refs), unresolved


def bundle_datas(root: str = PROJECT_ROOT):
    """PyInstaller ``datas`` entries: every file in each asset folder, as ``(source, folder)``."""
    datas = []
    for folder in ASSET_FOLDERS:
        folder_path = _to_path(root, folder)
        if not os.path.isdir(folder_path):
            continue
        for name in sorted(os.listdir(folder_path)):
            path = os.path.join(folder_path, name)
            if not name.startswith(".") and os.path.isfile(path):
                datas.append((path, folder))
    return datas


def bundled_assets(datas) -> set[str]:
    """Project-style paths that a list of ``datas`` entries places in the build."""
    return {f"{dest}/{os.path.basename(src)}" for src, dest in datas}


def coverage(datas, root: str = PROJECT_ROOT) -> dict:
    """Compare what the code opens with what ``datas`` bundles."""
    referenced, unresolved = referenced_assets(root)
    bundled = bundled_assets(datas)
    missing_on_disk = [rel for rel in referenced if not os.path.isfile(_to_path(root, rel))]
    not_bundled = [rel for rel in referenced if rel not in bundled and rel not in missing_on_disk]
    return {
        "referenced": referenced,
        "bundled": sorted(bundled),
        "unused": sorted(bundled - set(referenced)),
        "missing_on_disk": missing_on_disk,
        "not_bundled": not_bundled,
        "unresolved": unresolved,
    }


def problems(report: dict) -> list[str]:
    """Human-readable problems in a coverage report; an empty list means the check passes."""
    out = [f"referenced by the code but missing from the source tree: {rel}" for rel in report["missing_on_disk"]]
    out += [f"referenced by the code but not bundled by the spec: {rel}" for rel in report["not_bundled"]]
    out += [f"sound name is not a literal, so the file it opens is unknown: {site}" for site in report["unresolved"]]
    return out


def verify_bundle(datas, root: str = PROJECT_ROOT) -> dict:
    """Return the coverage report, or raise RuntimeError listing every missing or unresolved asset."""
    report = coverage(datas, root)
    found = problems(report)
    if found:
        raise RuntimeError("asset coverage check failed:\n  " + "\n  ".join(found))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check that every asset the game opens is bundled.")
    parser.add_argument("--root", default=PROJECT_ROOT, help="project root (default: the folder of this file)")
    parser.add_argument("--list", action="store_true", help="print every asset path the code opens and exit")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    report = coverage(bundle_datas(root), root)
    found = problems(report)

    if args.list:
        for rel in report["referenced"]:
            print(rel)
    else:
        referenced = report["referenced"]
        sfx = [rel for rel in referenced if rel.startswith("assets/audio/sfx_")]
        music = [rel for rel in referenced if rel.startswith("assets/audio/music_")]
        fonts = [rel for rel in referenced if rel.startswith("assets/fonts/")]
        print(f"Asset coverage for {root}")
        print(f"  opened by the code : {len(referenced)} (fonts {len(fonts)}, music {len(music)}, sfx {len(sfx)})")
        print(f"  bundled from disk  : {len(report['bundled'])}")
        print(f"  bundled, not opened: {len(report['unused'])} {report['unused']}")
        if found:
            print(f"FAILED: {len(found)} problem(s)")
        else:
            print("OK: every asset the code opens is on disk and bundled.")

    for line in found:
        print(f"ERROR: {line}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
