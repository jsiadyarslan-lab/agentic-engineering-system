"""E1 code_analysis domain — deterministic static analysis (D-02 = C).

The code_analysis implementation is deliberately *deterministic*:
AST-based module analysis and import-graph construction only. No
models (D-09 = A: none in E1), no dynamic execution (``ast.parse``
is parsing, not execution), no network, no process spawning.

Fail-closed rules:

- A file that fails to parse yields a failed analysis entry with a
  truthful diagnostic — never a partial or guessed result;
- Binary or oversized files are rejected by the shared path policy
  before parsing;
- The import graph only draws edges between files inside the granted
  root; external roots are listed, never resolved or fetched.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from contracts.operations import (
    FileAccessEvidence,
    PathPolicy,
    PathPolicyViolation,
)


@dataclass(frozen=True)
class SymbolDef:
    """One top-level definition in a Python module."""

    name: str
    line: int


@dataclass(frozen=True)
class ModuleAnalysis:
    """Static analysis of one Python module (deterministic)."""

    path: str
    loc: int
    import_roots: tuple[str, ...]
    imports: tuple[str, ...]
    classes: tuple[SymbolDef, ...]
    functions: tuple[SymbolDef, ...]
    has_docstring: bool
    syntax_error: str = ""


def analyze_python_source(source: bytes, *, path: str) -> ModuleAnalysis:
    """Analyze Python source bytes; syntax errors are fail-closed entries."""
    loc = source.count(b"\n")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        return ModuleAnalysis(
            path=path,
            loc=loc,
            import_roots=(),
            imports=(),
            classes=(),
            functions=(),
            has_docstring=False,
            syntax_error=f"undecodable as utf-8: {error}",
        )
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as error:
        return ModuleAnalysis(
            path=path,
            loc=loc,
            import_roots=(),
            imports=(),
            classes=(),
            functions=(),
            has_docstring=False,
            syntax_error=f"line {error.lineno}: {error.msg}",
        )
    imports: list[str] = []
    roots: list[str] = []
    classes: list[SymbolDef] = []
    functions: list[SymbolDef] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                roots.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            prefix = "." * level
            name = prefix + module
            imports.append(name)
            roots.append(module.split(".")[0] if module else prefix)
            for alias in node.names:
                # 'from . import x' → '.x'; 'from ..pkg import y' → '..pkg.y'
                joined = (
                    f"{name}{alias.name}" if name.endswith(".") else f"{name}.{alias.name}"
                )
                imports.append(joined)
        elif isinstance(node, ast.ClassDef):
            classes.append(SymbolDef(name=node.name, line=node.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(SymbolDef(name=node.name, line=node.lineno))
    return ModuleAnalysis(
        path=path,
        loc=loc,
        import_roots=tuple(sorted(set(roots))),
        imports=tuple(sorted(set(imports))),
        classes=tuple(classes),
        functions=tuple(functions),
        has_docstring=ast.get_docstring(tree) is not None,
    )


def analyze_python_file(
    target: str, policy: PathPolicy
) -> tuple[ModuleAnalysis, FileAccessEvidence]:
    """Analyze one granted Python file under the path policy."""
    data, evidence = policy.read_file(target)
    analysis = analyze_python_source(data, path=evidence.path)
    return analysis, evidence


def analyze_python_tree(
    root: Path, policy: PathPolicy
) -> tuple[tuple[ModuleAnalysis, ...], tuple[FileAccessEvidence, ...]]:
    """Analyze every ``.py`` file under a granted root (sorted order)."""
    files = [path for path in policy.list_tree(root) if path.suffix == ".py"]
    analyses: list[ModuleAnalysis] = []
    evidence: list[FileAccessEvidence] = []
    for path in files:
        analysis, access = analyze_python_file(str(path), policy)
        analyses.append(analysis)
        evidence.append(access)
    return tuple(analyses), tuple(evidence)


@dataclass(frozen=True)
class ImportGraphEdge:
    """One intra-root import edge (from module → to module)."""

    from_module: str
    to_module: str


@dataclass(frozen=True)
class ImportGraph:
    """Deterministic import graph of a granted root."""

    root: str
    modules: tuple[str, ...]
    edges: tuple[ImportGraphEdge, ...]
    external_roots: tuple[str, ...]
    syntax_errors: tuple[str, ...]

    def to_plain(self) -> dict[str, object]:
        return {
            "root": self.root,
            "modules": list(self.modules),
            "edges": [
                {"from": edge.from_module, "to": edge.to_module}
                for edge in self.edges
            ],
            "external_roots": list(self.external_roots),
            "syntax_errors": list(self.syntax_errors),
        }


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else path.stem


def build_import_graph(
    root: Path, policy: PathPolicy
) -> tuple[ImportGraph, tuple[FileAccessEvidence, ...]]:
    """Build the import graph for ``.py`` files under a granted root.

    Edges connect modules inside the root only; imports of external
    roots are collected in ``external_roots`` (never resolved).
    Relative imports map to their source module's package.
    """
    root_resolved = Path(root).resolve()
    analyses, evidence = analyze_python_tree(root, policy)
    module_names = {
        analysis.path: _module_name(root_resolved, Path(analysis.path))
        for analysis in analyses
    }
    known_modules = frozenset(module_names.values())
    edges: list[ImportGraphEdge] = []
    external: set[str] = set()
    syntax_errors: list[str] = []
    for analysis in analyses:
        source_module = module_names[analysis.path]
        if analysis.syntax_error:
            syntax_errors.append(f"{analysis.path}: {analysis.syntax_error}")
            continue
        package = source_module.rpartition(".")[0]
        for imported in analysis.imports:
            target_module = imported.lstrip(".")
            dots = len(imported) - len(target_module)
            if dots and package:
                # resolve relative import against the source package
                base = package.split(".")
                if dots - 1 > len(base):
                    continue
                resolved_base = base[: len(base) - (dots - 1)]
                target_module = ".".join(resolved_base + [target_module]) if target_module else ".".join(resolved_base)
            if target_module in known_modules and target_module != source_module:
                edges.append(
                    ImportGraphEdge(
                        from_module=source_module, to_module=target_module
                    )
                )
            elif target_module and not imported.startswith("."):
                external.add(target_module.split(".")[0])
    graph = ImportGraph(
        root=str(root_resolved),
        modules=tuple(sorted(known_modules)),
        edges=tuple(sorted(edges, key=lambda edge: (edge.from_module, edge.to_module))),
        external_roots=tuple(sorted(external)),
        syntax_errors=tuple(syntax_errors),
    )
    return graph, evidence


__all__ = [
    "ImportGraph",
    "ImportGraphEdge",
    "ModuleAnalysis",
    "SymbolDef",
    "analyze_python_file",
    "analyze_python_source",
    "analyze_python_tree",
    "build_import_graph",
]
