# spores

> An interactive TUI for exploring Arch Linux package dependencies.

Built with [Textual](https://github.com/Textualize/textual). Reads directly from `/var/lib/pacman/local` — no subprocesses, no `pacman -Qi` calls, instant startup.

---

## Features

- **Dependency tree** — expand any installed package and walk its full dep graph
- **Reverse mode** — flip the tree to see what depends on a given package
- **"Why is this here?"** — BFS traces any non-explicit dep back to the explicit package that pulled it in
- **Five filter views** — all packages, explicit only, dependency only, orphans, sorted by disk size
- **Detail pane** — version, description, install date, disk size, provides, deps / needed-by list
- **Fuzzy search** — prefix-match then substring-match against all installed packages
- **Zero subprocess overhead** — only three `pacman -Q` calls at startup for installed/explicit/orphan sets; everything else is direct file reads

---

## Requirements

- An Arch-based distro (Arch, Manjaro, EndeavourOS, Garuda, etc.)
- Python 3.11+
- [Textual](https://github.com/Textualize/textual)

---

## Installation

```bash
# 1. Clone or copy spores.py somewhere on your PATH
git clone https://github.com/you/spores
cd spores

# 2. Install the only dependency
pip install textual

# 3. Run
python spores.py
```

To make it available as a command:

```bash
mkdir -p ~/.local/bin
chmod +x spores.py
ln -sf "$(pwd)/spores.py" ~/.local/bin/spores
```

Then make sure `~/.local/bin` is on your PATH permanently. Which file to edit depends on your shell:

```bash
# zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshenv

# bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# fish
fish_add_path ~/.local/bin
```

Restart your terminal and `spores` should be available everywhere.

---

## Usage

```bash
# Open the package browser (splash view)
spores

# Jump directly into a specific package
spores python
spores firefox
```

---

## Keybindings

| Key | Action |
|-----|--------|
| `↵` | Open / explore the searched package |
| `ctrl+r` | Toggle reverse dependency mode |
| `ctrl+f` | Focus the search bar |
| `ctrl+e` | Expand all nodes |
| `ctrl+l` | Collapse all nodes |
| `ctrl+a` | Filter: all packages |
| `ctrl+x` | Filter: explicit packages only |
| `ctrl+d` | Filter: dependency packages only |
| `ctrl+o` | Filter: orphaned packages |
| `ctrl+s` | Filter: sort all packages by disk size |
| `escape` | Clear search input / return to splash |
| `q` | Quit |

---

## Views

### Splash (package list)

The default view on launch. Lists all installed packages in the tree. Use the filter bindings to narrow the list:

- **All** — every installed package, alphabetical
- **Explicit** — packages you installed intentionally (`pacman -Qe`)
- **Deps** — packages installed as dependencies only
- **Orphans** — packages with no remaining dependents (`pacman -Qdt`)
- **By size** — all packages sorted by installed size descending; packages over 100 MB are highlighted red, over 10 MB yellow

### Package explorer

Press `↵` on any search result to enter the explorer for that package. The left pane becomes a live dependency tree rooted at that package. Nodes expand on click or keyboard navigation. Press `escape` to return to the splash.

### Reverse mode (`ctrl+r`)

Flips the direction of the tree. Instead of "what does this package depend on", it shows "what depends on this package". Works in both the splash list and the per-package explorer. The detail pane switches its dep list to a **NEEDED BY** list accordingly.

### Detail pane

Selecting any node (or opening a package) populates the right pane with:

- Package name, version, description
- Install type (explicit / dependency), orphan flag
- Installed size, install date
- **WHY IS THIS HERE** — for non-explicit packages, a BFS chain showing the shortest path back to the explicit package that caused it to be installed
- **PROVIDES** — virtual packages this package satisfies
- **DEPENDS ON** / **NEEDED BY** — up to 20 entries, with overflow count

---

## Color coding

| Color | Meaning |
|-------|---------|
| Purple / bold | Explicit packages |
| Slate blue | Regular dependency packages |
| Red | Orphaned packages |
| Dim grey | Packages referenced in deps but not installed |

---

## How it works

On startup spores runs three lightweight `pacman -Q` calls to build three sets (installed, explicit, orphans), then reads every `desc` file under `/var/lib/pacman/local/` directly to build an in-memory database of name → version, size, and dependency list. The reverse dependency map is derived from that database in a single pass. All subsequent tree expansion and detail lookups hit only the in-memory structures or individual `desc` files — no further pacman invocations.

The "why is this here" chain is a BFS over the pre-built reverse map, stopping at the first explicit package encountered.

---

## Project structure

```
spores/
├── spores.py    # entire application — single file
└── README.md
```

---

## License

MIT
