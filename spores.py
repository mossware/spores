#!/usr/bin/env python3
"""
spores — Arch Linux package explorer
Interactive TUI built with Textual.

Requirements:
    pip install textual

Usage:
    python spores.py               # interactive search
    python spores.py python        # open package directly
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import deque
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Footer, Header, Input, Label, LoadingIndicator,
    Static, Tree,
)
from textual.widgets.tree import TreeNode
from textual.worker import get_current_worker


# CSS

CSS = """
/* ── Base ── */
Screen {
    background: #080B14;
    layers: base overlay;
}

/* ── Layout ── */
#layout {
    layout: horizontal;
    height: 1fr;
}

#left-pane {
    width: 1fr;
    min-width: 32;
    border: solid #1E293B;
    border-title-color: #7C3AED;
    border-title-style: bold;
    background: #0B0F1A;
    padding: 0 1;
}

#right-pane {
    width: 42;
    border: solid #1E293B;
    border-title-color: #7C3AED;
    border-title-style: bold;
    background: #0B0F1A;
    padding: 1 2;
}

/* ── Search bar ── */
#search-bar {
    height: 3;
    padding: 1 2;
    background: #0B0F1A;
    border-bottom: solid #1E293B;
}

#search-bar Input {
    background: #080B14;
    border: tall #1E293B;
    color: #E2E8F0;
    width: 1fr;
}

#search-bar Input:focus {
    border: tall #7C3AED;
}

#search-hint {
    color: #334155;
    margin-left: 1;
    width: auto;
    content-align: center middle;
    height: 1;
    margin-top: 1;
}

/* ── Tree ── */
Tree {
    background: transparent;
    color: #94A3B8;
    padding: 0;
    scrollbar-color: #1E293B;
    scrollbar-color-hover: #7C3AED;
}

Tree > .tree--guides {
    color: #1E293B;
}

Tree > .tree--guides-hover {
    color: #7C3AED;
}

Tree > .tree--cursor {
    background: #1E1040;
    color: #E2E8F0;
}

Tree:focus > .tree--cursor {
    background: #2D1B6B;
    color: #E2E8F0;
}

/* ── Detail pane sections ── */
.detail-name {
    color: #C084FC;
    text-style: bold;
    padding-bottom: 1;
}

.detail-version {
    color: #818CF8;
    text-style: italic;
}

.detail-desc {
    color: #94A3B8;
    padding: 1 0;
}

.section-header {
    color: #475569;
    text-style: bold;
    margin-top: 1;
    border-bottom: solid #1E293B;
    padding-bottom: 0;
}

.kv-key {
    color: #475569;
    width: 12;
}

.kv-val {
    color: #CBD5E1;
}

.kv-val-accent {
    color: #C084FC;
    text-style: bold;
}

.kv-val-green {
    color: #34D399;
}

.kv-val-red {
    color: #F87171;
}

.kv-val-blue {
    color: #38BDF8;
}

.kv-row {
    layout: horizontal;
    height: auto;
    margin-bottom: 0;
}

.reqby-item {
    color: #38BDF8;
    padding-left: 2;
}

.dep-item {
    color: #818CF8;
    padding-left: 2;
}

.empty-detail {
    color: #1E293B;
    content-align: center middle;
    height: 1fr;
    text-style: italic;
}

/* ── Status bar ── */
#status-bar {
    height: 1;
    background: #0B0F1A;
    border-top: solid #1E293B;
    padding: 0 2;
    layout: horizontal;
}

#status-left {
    color: #475569;
    width: 1fr;
    content-align: left middle;
}

#status-right {
    width: auto;
    content-align: right middle;
}

.status-ok { color: #34D399; }
.status-err { color: #F87171; }
.status-info { color: #818CF8; }

/* ── Loading ── */
LoadingIndicator {
    color: #7C3AED;
    background: transparent;
}

#loading-overlay {
    height: 1fr;
    content-align: center middle;
    color: #475569;
}

/* ── Footer ── */
Footer {
    background: #080B14;
    color: #334155;
    border-top: solid #1E293B;
}

Footer > .footer--key {
    background: #1E1040;
    color: #C084FC;
}

Footer > .footer--description {
    color: #475569;
}

/* ── Splash ── */
#splash {
    height: 1fr;
    content-align: center middle;
    background: #080B14;
    layout: vertical;
}

#splash-logo {
    color: #7C3AED;
    text-style: bold;
    content-align: center middle;
    width: 100%;
}

#splash-sub {
    color: #334155;
    content-align: center middle;
    width: 100%;
    margin-top: 1;
}
"""


# Data layer

@dataclass
class PkgInfo:
    name:        str
    version:     str       = "?"
    description: str       = ""
    size:        str       = "?"
    install_date:str       = "?"
    explicit:    bool      = False
    deps:        list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)
    provides:    list[str] = field(default_factory=list)
    is_orphan:   bool      = False
    installed:   bool      = True


def _run(cmd: list[str], timeout: int = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _run_set(cmd: list[str]) -> set[str]:
    out = _run(cmd)
    return {line.split()[0] for line in out.splitlines() if line.strip()}


def get_installed() -> set[str]:
    return _run_set(["pacman", "-Q"])


def get_explicit() -> set[str]:
    return _run_set(["pacman", "-Qe"])


def get_orphans() -> set[str]:
    return _run_set(["pacman", "-Qdt"])


def get_direct_deps(package: str, db: dict[str, dict], reverse: bool = False) -> list[str]:
    if not reverse:
        return list(db.get(package, {}).get("deps", []))
    result: list[str] = []
    for name, info in db.items():
        if package in info.get("deps", []):
            result.append(name)
    return result


def _parse_desc(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("%") and line.endswith("%"):
            tag = line[1:-1]
            i += 1
            vals: list[str] = []
            while i < len(lines) and lines[i].strip():
                vals.append(lines[i].strip())
                i += 1
            result[tag] = "\n".join(vals)
        i += 1
    return result


def _find_pkg_dir(package: str) -> Path | None:
    db_path = Path("/var/lib/pacman/local")
    if not db_path.exists():
        return None
    for entry in db_path.iterdir():
        parts = entry.name.rsplit("-", 2)
        if len(parts) >= 2 and parts[0] == package:
            return entry
    return None


def get_pkg_info(package: str, explicit_set: set[str], orphan_set: set[str],
                 db: dict[str, dict]) -> PkgInfo:
    pkg_dir = _find_pkg_dir(package)
    if pkg_dir is None:
        return PkgInfo(name=package, installed=False)

    desc_file = pkg_dir / "desc"
    if not desc_file.exists():
        return PkgInfo(name=package, installed=False)

    try:
        desc = _parse_desc(desc_file.read_text(errors="replace"))
    except OSError:
        return PkgInfo(name=package, installed=False)

    def desc_list(tag: str) -> list[str]:
        val = desc.get(tag, "")
        return [x.strip() for x in val.splitlines() if x.strip()]

    def strip_version(s: str) -> str:
        return re.split(r"[>=<!]", s)[0].strip()

    version      = desc.get("VERSION", "?").strip() or "?"
    description  = desc.get("DESC", "").strip()
    _idate_raw   = desc.get("INSTALLDATE", "").strip()
    try:
        install_date = datetime.fromtimestamp(int(_idate_raw)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        install_date = _idate_raw or "?"
    size_bytes   = int(desc.get("SIZE", "0").strip() or "0")
    size_str     = fmt_size(size_bytes)
    provides     = [strip_version(p) for p in desc_list("PROVIDES")]

    deps        = [strip_version(d) for d in desc.get("DEPENDS",    "").splitlines() if d.strip()]
    required_by = [r.strip()        for r in desc.get("REQUIREDBY", "").splitlines() if r.strip()]

    return PkgInfo(
        name=package,
        version=version,
        description=description,
        size=size_str,
        install_date=install_date,
        explicit=(package in explicit_set),
        deps=deps,
        required_by=required_by,
        provides=provides,
        is_orphan=(package in orphan_set),
        installed=True,
    )


def load_pacman_db() -> dict[str, dict]:
    db: dict[str, dict] = {}
    db_path = Path("/var/lib/pacman/local")
    if not db_path.exists():
        return db

    for pkg_dir in db_path.iterdir():
        if not pkg_dir.is_dir():
            continue
        desc_file = pkg_dir / "desc"
        if not desc_file.exists():
            continue
        try:
            desc = _parse_desc(desc_file.read_text(errors="replace"))
        except OSError:
            continue

        name    = desc.get("NAME", "").strip()
        version = desc.get("VERSION", "").strip()
        size_s  = desc.get("SIZE", "0").strip()

        if not name:
            parts = pkg_dir.name.rsplit("-", 2)
            name = parts[0] if parts else ""
        if not name:
            continue

        try:
            size_bytes = int(size_s)
        except ValueError:
            size_bytes = 0

        deps: list[str] = []
        for line in desc.get("DEPENDS", "").splitlines():
            dep_name = re.split(r"[>=<!]", line.strip())[0].strip()
            if dep_name:
                deps.append(dep_name)

        db[name] = {"size_bytes": size_bytes, "version": version, "deps": deps}

    return db


def fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f} KB"
    return f"{size_bytes} B"


def build_reverse_map(db: dict[str, dict]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for name, info in db.items():
        for dep in info.get("deps", []):
            rev.setdefault(dep, []).append(name)
    return rev


def find_why_chain(pkg: str, explicit: set[str],
                   rev_map: dict[str, list[str]]) -> list[str]:
    if pkg in explicit:
        return []

    visited = {pkg}
    queue: deque[tuple[str, list[str]]] = deque([(pkg, [pkg])])

    while queue:
        node, path = queue.popleft()
        for parent in rev_map.get(node, []):
            if parent in visited:
                continue
            visited.add(parent)
            new_path = path + [parent]
            if parent in explicit:
                return new_path
            queue.append((parent, new_path))

    return []


@dataclass
class NodeMeta:
    name:     str
    expanded: bool  = False
    loaded:   bool  = False


# Detail panel

class DetailPane(ScrollableContainer):

    DEFAULT_CSS = "DetailPane { overflow-y: auto; }"

    def compose(self) -> ComposeResult:
        yield Static("Select a package\nto see details", classes="empty-detail")

    def show_loading(self) -> None:
        self.query("*").remove()
        self.mount(LoadingIndicator())

    def show_empty(self) -> None:
        self.query("*").remove()
        self.mount(Static("Select a package\nto see details", classes="empty-detail"))

    def show_info(self, info: PkgInfo, reverse: bool,
                  why_chain: list[str] | None = None) -> None:
        self.query("*").remove()

        widgets: list[Widget] = []

        widgets.append(Static(f"[bold]{info.name}[/bold]", classes="detail-name"))
        widgets.append(Static(info.version, classes="detail-version"))

        if info.description and info.description != "?":
            widgets.append(Static(info.description, classes="detail-desc"))

        widgets.append(Static("INFO", classes="section-header"))

        def kv(key: str, val: str, val_class: str = "kv-val") -> Widget:
            return Horizontal(
                Static(key, classes="kv-key"),
                Static(val, classes=val_class),
                classes="kv-row",
            )

        explicit_label = "explicit" if info.explicit else "dependency"
        explicit_class = "kv-val-green" if info.explicit else "kv-val-blue"

        widgets.append(kv("Install", explicit_label, explicit_class))

        if info.is_orphan:
            widgets.append(kv("Orphan", "yes", "kv-val-red"))

        if info.size != "?":
            widgets.append(kv("Size", info.size))

        if info.install_date != "?":
            widgets.append(kv("Installed", info.install_date))

        if why_chain and len(why_chain) > 1:
            widgets.append(Static("WHY IS THIS HERE", classes="section-header"))
            for i, step in enumerate(why_chain):
                if i == 0:
                    arrow = "  "
                else:
                    arrow = "  [#334155]↑[/] "
                is_last = (i == len(why_chain) - 1)
                if is_last:
                    widgets.append(Static(
                        f"{arrow}[bold #818CF8]{step}[/] [#334155](explicit)[/]",
                        classes="dep-item",
                    ))
                else:
                    widgets.append(Static(f"{arrow}[#94A3B8]{step}[/]", classes="dep-item"))
        elif info.explicit:
            widgets.append(Static("WHY IS THIS HERE", classes="section-header"))
            widgets.append(Static("  [#34D399]you installed it[/]", classes="dep-item"))

        if info.provides:
            widgets.append(Static("PROVIDES", classes="section-header"))
            for p in info.provides[:6]:
                widgets.append(Static(f"  {p}", classes="dep-item"))

        if reverse:
            if info.required_by:
                count = len(info.required_by)
                widgets.append(Static(f"NEEDED BY ({count})", classes="section-header"))
                for r in info.required_by[:20]:
                    widgets.append(Static(f"  {r}", classes="reqby-item"))
                if count > 20:
                    widgets.append(Static(f"  … and {count-20} more", classes="kv-key"))
            else:
                widgets.append(Static("NEEDED BY", classes="section-header"))
                widgets.append(Static("  nothing", classes="kv-key"))
        else:
            if info.deps:
                count = len(info.deps)
                widgets.append(Static(f"DEPENDS ON ({count})", classes="section-header"))
                for d in info.deps[:20]:
                    widgets.append(Static(f"  {d}", classes="dep-item"))
                if count > 20:
                    widgets.append(Static(f"  … and {count-20} more", classes="kv-key"))
            else:
                widgets.append(Static("DEPENDS ON", classes="section-header"))
                widgets.append(Static("  nothing", classes="kv-key"))

        self.mount(*widgets)


# Main app

class Spore(App):

    CSS = CSS

    TITLE = "spore"
    SUB_TITLE = "arch deps"

    BINDINGS = [
        Binding("ctrl+r", "toggle_reverse",      "Reverse deps",  show=True),
        Binding("ctrl+f", "focus_search",        "Search",        show=True),
        Binding("ctrl+e", "expand_all",          "Expand all",    show=True),
        Binding("ctrl+l", "collapse_all",        "Collapse",      show=True),
        Binding("ctrl+a", "filter('all')",       "All",           show=True),
        Binding("ctrl+x", "filter('explicit')",  "Explicit",      show=True),
        Binding("ctrl+d", "filter('deps')",      "Deps",          show=True),
        Binding("ctrl+o", "filter('orphans')",   "Orphans",       show=True),
        Binding("ctrl+s", "filter('size')",      "By size",       show=True),
        Binding("escape", "clear_search",      "Clear / reset",     show=True),
        Binding("q",      "quit",              "Quit",              show=True),
    ]

    reverse_mode: reactive[bool] = reactive(False)
    filter_mode:  reactive[str]  = reactive("all")
    status_msg:   reactive[str]  = reactive("")
    status_cls:   reactive[str]  = reactive("status-info")

    def __init__(self, initial_package: str = ""):
        super().__init__()
        self._initial_package  = initial_package.strip()
        self._installed:  set[str] = set()
        self._explicit:   set[str] = set()
        self._orphans:    set[str] = set()
        self._db:         dict[str, dict] = {}
        self._rev_map:    dict[str, list[str]] = {}
        self._current_pkg: str     = ""

    # Compose

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="search-bar"):
            yield Input(
                placeholder="  search package…  ( ↵ to explore )",
                id="search-input",
            )
            yield Static("ctrl+r reverse  •  ctrl+e expand  •  ctrl+l collapse  •  q quit", id="search-hint")

        with Horizontal(id="layout"):
            with Container(id="left-pane"):
                tree = Tree("", id="dep-tree")
                tree.show_root = False
                tree.guide_depth = 3
                yield tree

            with Container(id="right-pane"):
                yield DetailPane(id="detail-pane")

        with Horizontal(id="status-bar"):
            yield Static("", id="status-left")
            yield Static("", id="status-right")

        yield Footer()

    # Mount / startup

    def on_mount(self) -> None:
        self.query_one("#left-pane").border_title = " ❯ tree "
        self.query_one("#right-pane").border_title = " ❯ detail "
        self._load_pacman_state()

    @work(thread=True)
    def _load_pacman_state(self) -> None:
        self._set_status("loading pacman database…", "status-info")
        self._installed = get_installed()
        self._explicit  = get_explicit()
        self._orphans   = get_orphans()
        self._db        = load_pacman_db()
        if not self._installed:
            self._installed = set(self._db.keys())
        self._rev_map   = build_reverse_map(self._db)

        if self._initial_package:
            self.call_from_thread(self._open_package, self._initial_package)
        else:
            self.call_from_thread(self._show_splash)

    def _show_splash(self) -> None:
        tree = self.query_one("#dep-tree", Tree)
        tree.clear()
        root = tree.root
        root.expand()

        mode = self.filter_mode

        if mode == "explicit":
            pkgs = sorted(self._explicit)
        elif mode == "deps":
            pkgs = sorted(self._installed - self._explicit)
        elif mode == "orphans":
            pkgs = sorted(self._orphans)
        elif mode == "size":
            pkgs = sorted(
                self._installed,
                key=lambda p: self._db.get(p, {}).get("size_bytes", 0),
                reverse=True,
            )
        else:
            pkgs = sorted(self._installed)

        for pkg in pkgs:
            if mode == "size":
                size_bytes = self._db.get(pkg, {}).get("size_bytes", 0)
                size_str   = fmt_size(size_bytes)
                if size_bytes >= 100_000_000:
                    size_tag = f"[bold #F87171]{size_str:>9}[/]"
                elif size_bytes >= 10_000_000:
                    size_tag = f"[#FBBF24]{size_str:>9}[/]"
                else:
                    size_tag = f"[#475569]{size_str:>9}[/]"
                label = f"{size_tag}  {self._fmt_node(pkg)}"
            else:
                label = self._fmt_node(pkg)

            node = root.add(label, data=NodeMeta(name=pkg))
            has_deps = bool(self._db.get(pkg, {}).get("deps"))
            node.allow_expand = has_deps or self.reverse_mode

        FILTER_LABELS = {
            "all":      "[#475569]all[/]",
            "explicit": "[#818CF8]explicit[/]",
            "deps":     "[#94A3B8]deps[/]",
            "orphans":  "[#F87171]orphans[/]",
            "size":     "[#FBBF24]by size ↓[/]",
        }
        filter_str = FILTER_LABELS[mode]
        self._set_status(
            f"  {len(pkgs)} packages  •  filter: {filter_str}"
            f"  [#334155](^a all  ^x explicit  ^d deps  ^o orphans  ^s size)[/]",
            "status-info",
        )
        self.query_one("#search-input", Input).focus()

    # Node formatting

    def _fmt_node(self, name: str) -> str:
        parts = []
        if name in self._explicit:
            parts.append(f"[bold #818CF8]{name}[/]")
        elif name in self._orphans:
            parts.append(f"[#F87171]{name}[/]")
        elif name not in self._installed:
            parts.append(f"[#475569]{name}[/]")
        else:
            parts.append(f"[#94A3B8]{name}[/]")
        return "".join(parts)

    # Tree expansion

    @on(Tree.NodeExpanded)
    def handle_expand(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        meta = node.data
        if not isinstance(meta, NodeMeta):
            return
        if meta.loaded:
            return
        meta.loaded = True
        self._load_children(node, meta.name)

    @work(thread=True)
    def _load_children(self, node: TreeNode, name: str) -> None:
        worker = get_current_worker()
        if self.reverse_mode:
            deps = list(self._rev_map.get(name, []))
        else:
            deps = list(self._db.get(name, {}).get("deps", []))

        if worker.is_cancelled:
            return

        def update() -> None:
            node.remove_children()
            if not deps:
                node.allow_expand = False
                node.collapse()
                node.add_leaf("  [#334155]no dependencies[/]")
                return
            for dep in deps:
                child = node.add(
                    self._fmt_node(dep),
                    data=NodeMeta(name=dep),
                )
                child.allow_expand = (dep in self._installed)

        self.call_from_thread(update)

    # Search

    def _open_package(self, name: str) -> None:
        if name not in self._installed:
            self._set_status(f"  '{name}' is not installed", "status-err")
            return

        tree = self.query_one("#dep-tree", Tree)
        tree.clear()
        root = tree.root

        label = f"[bold #C084FC]◉ {name}[/]"
        node = root.add(label, data=NodeMeta(name=name))
        node.allow_expand = True
        node.expand()

        self._current_pkg = name
        self.query_one("#left-pane").border_title = f" ❯ {name} "
        mode = "reverse" if self.reverse_mode else "deps"
        self._set_status(f"  exploring {name}  [{mode}]", "status-info")
        self._load_detail(name)

    @work(thread=True)
    def _load_detail(self, name: str) -> None:
        detail = self.query_one("#detail-pane", DetailPane)
        self.call_from_thread(detail.show_loading)

        info      = get_pkg_info(name, self._explicit, self._orphans, self._db)
        why_chain = find_why_chain(name, self._explicit, self._rev_map)

        def update():
            detail.show_info(info, self.reverse_mode, why_chain)

        self.call_from_thread(update)

    # Event handlers

    @on(Tree.NodeSelected)
    def handle_select(self, event: Tree.NodeSelected) -> None:
        meta = event.node.data
        if not isinstance(meta, NodeMeta):
            return
        self._load_detail(meta.name)

    @on(Input.Submitted, "#search-input")
    def handle_search(self, event: Input.Submitted) -> None:
        query = event.value.strip().lower()
        if not query:
            return
        if query in self._installed:
            self._open_package(query)
            event.input.clear()
            self.query_one("#dep-tree", Tree).focus()
        else:
            matches = [p for p in self._installed if p.startswith(query)]
            if not matches:
                matches = [p for p in self._installed if query in p]
            if matches:
                self._open_package(matches[0])
                event.input.value = matches[0]
                self.query_one("#dep-tree", Tree).focus()
            else:
                self._set_status(f"  '{query}' not found in installed packages", "status-err")

    # Actions

    def action_filter(self, mode: str) -> None:
        if self._current_pkg:
            return
        self.filter_mode = mode
        self._show_splash()

    def action_toggle_reverse(self) -> None:
        self.reverse_mode = not self.reverse_mode
        mode = "[bold #F87171]reverse[/]" if self.reverse_mode else "[bold #34D399]forward[/]"
        self._set_status(f"  mode → {mode}", "status-info")
        if self._current_pkg:
            self._open_package(self._current_pkg)

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_expand_all(self) -> None:
        tree = self.query_one("#dep-tree", Tree)
        for node in tree.root.children:
            node.expand_all()

    def action_collapse_all(self) -> None:
        tree = self.query_one("#dep-tree", Tree)
        for node in tree.root.children:
            node.collapse_all()

    def action_clear_search(self) -> None:
        inp = self.query_one("#search-input", Input)
        if inp.value:
            inp.clear()
            inp.focus()
        elif self._current_pkg:
            self._current_pkg = ""
            self.filter_mode  = "all"
            tree = self.query_one("#dep-tree", Tree)
            tree.clear()
            self._show_splash()
            self.query_one("#right-pane").border_title = " ❯ detail "
            self.query_one("#detail-pane", DetailPane).show_empty()

    # Status helper

    def _set_status(self, msg: str, cls: str = "status-info") -> None:
        try:
            lbl = self.query_one("#status-left", Static)
            lbl.update(msg)
            lbl.remove_class("status-ok", "status-err", "status-info")
            lbl.add_class(cls)
        except NoMatches:
            pass

    # Reactive watchers

    def watch_reverse_mode(self, val: bool) -> None:
        try:
            mode_str = " [reverse] " if val else " [forward] "
            self.query_one("#right-pane").border_title = f" ❯ detail{mode_str}"
        except NoMatches:
            pass


# Entry point

def main() -> None:
    pkg = sys.argv[1] if len(sys.argv) > 1 else ""
    app = Spore(initial_package=pkg)
    app.run()


if __name__ == "__main__":
    main()
