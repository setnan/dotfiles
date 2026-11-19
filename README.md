# Dotfiles

My dotfiles for macOS: zsh, git, starship, micro, tmux, Sublime Text, Zed and a set of
Alfred workflows.

Based on [ringvold/dotfiles](https://github.com/ringvold/dotfiles), which in turn is
based on [anishathalye/dotfiles](https://github.com/anishathalye/dotfiles).

## Installation

```sh
git clone --recursive git@github.com:setnan/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
brew bundle   # installs the tools in the Brewfile
./install     # symlinks everything into place
```

[Dotbot](https://github.com/anishathalye/dotbot) creates the symlinks defined in
`install.conf.yaml`. Run `./install` again after changing that file.

## Layout

- `zshenv.zsh` - sets `ZDOTDIR` to `~/.config/zsh`
- `zsh/zshrc.zsh` - the main zshrc, sources the files below in order
- `zsh/settings.zsh` - general zsh options and history
- `zsh/lib/` - completion, key bindings, colours, directory aliases
- `zsh/zgen.zsh` - plugins via [zgenom](https://github.com/jandamm/zgenom)
- `zsh/aliases.zsh` - aliases and functions
- `zsh/plugins_after.zsh` - starship, zoxide, fzf, direnv
- `shell/bootstrap.sh` - PATH and editor
- `gitconfig`, `gitignore_global`, `editorconfig`, `starship.toml`, `micro/`, `tmux.conf`
- `sublime/` - Sublime Text settings (Catppuccin Latte/Mocha, JetBrains Mono Nerd Font)
- `zed/` - Zed settings
- `bin/` - small scripts, symlinked to `~/bin`
- `launchd/` - background jobs (launchd agents)
- `dash/` - builds a Fly.io docset for Dash
- `alfred/` - Alfred's sync folder with every workflow (see [Alfred workflows](#alfred-workflows))

## Alfred workflows

[Alfred](https://www.alfredapp.com) (with the Powerpack) syncs its whole preference
folder to `alfred/Alfred.alfredpreferences`, so the workflows in this repo *are* the live
ones. Point Alfred at it once: Alfred Preferences → Advanced → Set preferences folder →
`~/.dotfiles/alfred`. After editing a workflow outside Alfred's editor, restart Alfred
(`killall Alfred && open -a "Alfred 5"`).

Most workflows are plain Python 3 or zsh scripts with no dependencies beyond macOS.
Anything that needs extra tools says so below. The Brewfile installs the Homebrew ones;
[`uv`](https://docs.astral.sh/uv/) and the [`claude`](https://claude.com/claude-code) CLI
come from their own installers.
The UI text is in Norwegian, the keywords are what you type.

### Notes, time and writing

| Keyword | What it does |
|---|---|
| `ob` / `obsidian` | Search an Obsidian vault: recent notes when empty, otherwise title/path matches first, then full-text. ↩ opens in Obsidian, ⌘↩ opens Obsidian's own search, ⌥↩ reveals in Finder, ⌘C copies a `[[wikilink]]`. |
| `n` / `note` | Quick capture: adds `- [ ] text` under `## Notater` in an inbox note. Commas make several items. ⌘↩ sends it to the shopping list instead. |
| `h` / `handleliste` | Shopping list: appends a checkbox item, with store keywords that file it under a store heading and a trailing number as quantity (`milk 2`). URLs become Markdown links titled from the page. |
| `start` / `stop` / `pause` / `lu` / `edit` | **Time tracking** into one Markdown note (see below). |
| `sum` / `showsum` | Summarises the clipboard with Claude into a self-refreshing HTML page: key points, a plain-language version, an analogy, plus tables, bar charts or stat tiles when the content has numbers. Extra text after `sum` is an extra instruction. |
| `aak` / `hentak` | Keyword overview: `hentak` reads every workflow and custom web search and rebuilds a table (in a note) and an HTML page; `aak` opens the page. Your own notes in the table survive rebuilds. |
| `lorem <n>` | Copies exactly *n* characters of lorem ipsum (whole words, ends on a full stop). Default 250. |

**Time tracking** (`Timetracking`). The note is the source of truth: every project is a
`## heading` with a table of sessions and a **Sum** row per day (`h:mm` and decimal hours).
What is running lives in the note's frontmatter, so you can see and fix it in Obsidian.

- `start acme` starts a project and closes whatever was running. Typing a new name creates
  the project; an empty `start` lets you browse projects, most recent first, with today's
  and this week's totals.
- Forgot to start? Add a time: `start acme 8`, `start globex 0930`. `8`, `80`, `800`, `0800`
  and `8:00` all mean 08:00, `81` is 08:10, `815` is 08:15, two digits up to 23 are whole
  hours. The previous project is closed at that same time.
- `lu` / `lunch [time]` stops the project and starts the lunch project (configurable,
  default `intern`). `stop [time]` stops and shows a day summary.
- `pause [time]` closes the current session and remembers the project; `pause` again (or
  picking it in `start`) carries on with a new session.
- `edit acme 815 - 11` corrects today's row for that project; older days are edited in
  Obsidian.
- Delete a heading to remove a project, rename it to `<name>-archived` to hide it from
  suggestions. Sessions over midnight are split per date, sessions under a minute are not
  logged.

### AI

| Keyword | What it does |
|---|---|
| `cc <folder> [prompt]` | Starts Claude Code in a project (folders from zoxide) in a new Ghostty tab. ⌘↩ continues the last session. |
| `cr [search]` | Resumes a recent Claude Code session in a new Ghostty tab. |
| `ask <question>` | Short answer from Claude in Alfred's text view, also copied. ⌘↩ opens claude.ai. |
| Universal Actions | On selected text: fix spelling/grammar, translate, explain (via `claude -p`, no tools). |
| `cu` | Claude rate limits (5-hour and weekly window, reset times), the same data as `/usage`. Reads Claude Code's token from the keychain and talks only to api.anthropic.com. |
| `cx` | The same for Codex, from `~/.codex/auth.json`, talking only to chatgpt.com. |

Needs the `claude` CLI (and Ghostty for `cc`/`cr`).

### System

| Keyword | What it does |
|---|---|
| `stats [filter]` | Live machine status, refreshing every 2 s: CPU, memory pressure, disks, top processes, battery, LAN/Tailscale IP. `stats disk`, `stats minne` … filter it. |
| `kill [search]` | Running processes with hung apps (not responding, stopped, zombie) on top. ↩ quits (SIGTERM), ⌘↩ force-kills, ⌥↩ kills every process of that app. |
| `koffein` / `caffein` | Keep the Mac awake with Lungo, optionally armed for closing the lid with Clamshell, or turn both off. |
| `tema`, `lys`/`light`, `mørk`/`dark` | Toggle macOS light/dark appearance. |
| `rydd` | Saved window layouts across displays: `rydd lagre <name>` saves the current windows, `rydd` lists and restores. Layouts can get their own keyword. Layout files stay local. |
| `z` / `zed` | Toggles Zed settings, e.g. Copilot edit predictions. |
| `kon` / `kontakt` | Searches Contacts (name, phone, e-mail, company) without contacts cluttering default results. ↩ shows all fields, ⌘↩ calls/mails/opens in Maps. |

`koffein`, `tema` and `rydd` drive apps through System Events, so Alfred needs
Accessibility and Automation access.

### Audio recording and transcription

| Keyword | What it does |
|---|---|
| `record` / `rec` | Records system audio (BlackHole) and the default microphone as two tracks. `rec mute` records system audio only. |
| `stoprecording` | Stops, mixes the tracks (loudness-normalised, mic ducked while the other side talks) into `~/Downloads/<timestamp>.wav` and restores the audio output. |
| `transcribenb` / `transcribeen` | Transcribes the newest audio or video file in Downloads locally with whisper.cpp and the [NB-Whisper](https://huggingface.co/NbAiLab) model, with voice activity detection. |
| `hodetelefoner`, `høyttalere`, `jack`, `kun…` | Switch the output to a Multi-Output Device that includes BlackHole (for recording) or back to a plain device (normal volume keys). |

Needs `blackhole-2ch`, `sox`, `switchaudio-osx`, `ffmpeg`, `whisper.cpp`, the NB-Whisper
ggml model in `~/.whisper-models/` and Multi-Output Devices set up in Audio MIDI Setup.
Recording runs as one-shot launchd jobs, because Alfred itself can't get microphone access.

### Other tools

| Keyword | What it does |
|---|---|
| `sol` / `solar` | Physics calculator with units: `sol s=120km t=1.5h` gives speed, energy, power, electricity cost and more. Runs with `uv` + pint. |
| `air` / `luft` | Latest Airthings Wave Plus readings. `air 7` / `luftrapport 30` makes a PDF report with charts. Needs an Airthings API client ID/secret in the keychain. |
| `mtg <card>` | Magic: The Gathering card search via Scryfall. ⌘↩ browses all printings, ⇧↩ adds the card to a wishlist note. |
| `finn`, `fl`, `hexdocs`, `hexpm` | Custom web searches (finn.no, nearby finn.no, Hex docs and packages). |

Third-party workflows included: [1Password](https://github.com/alfredapp/1password-workflow)
(`1p`) and [Dash](https://kapeli.com/dash) (`dash` and one keyword per docset).

### Machine-specific settings

Paths to your own notes are set per workflow in Alfred (*Configure Workflow*). Alfred
saves them in each workflow's `prefs.plist`, which is gitignored, so the repo only holds
neutral defaults.

Values that have to live inside a tracked file (like the location filter in the `fl` web
search) are swapped for placeholders on commit by a git clean/smudge filter,
`bin/dotfiles-private-filter`. The real values sit in
`~/.config/dotfiles-private/filter.tsv` (`placeholder<TAB>real value`), and
`.gitattributes` lists the files it applies to. On a new machine:

```sh
git config filter.private.clean  "$HOME/.dotfiles/bin/dotfiles-private-filter clean"
git config filter.private.smudge "$HOME/.dotfiles/bin/dotfiles-private-filter smudge"
```

## Local overrides

These files are read when they exist and live outside the repo:

- `~/.zshrc_local_before` and `~/.zshrc_local_after`
- `~/.zgen_local` - extra zgenom plugins
- `~/.gitconfig_local` - e.g. a work identity
- `~/.secrets` - API keys and the like

## Debugging slow startup

Set `export ZSH_DEBUG=true` in `zshenv.zsh`, open a new shell, and run
`zsh/debug/sort_timings.zsh zsh_profile.*` on the log file it writes.
