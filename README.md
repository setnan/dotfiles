# Dotfiles

Mitt dotfiles-oppsett for macOS. Konfigurerer zsh, git, starship og micro.

Basert på [ringvold/dotfiles](https://github.com/ringvold/dotfiles), som igjen er
basert på [anishathalye/dotfiles](https://github.com/anishathalye/dotfiles).

## Installasjon

```sh
git clone --recursive git@github.com:setnan/dotfiles.git ~/.dotfiles
cd ~/.dotfiles
brew bundle   # installerer verktøy fra Brewfile
./install     # symlinker filene på plass
```

[Dotbot](https://github.com/anishathalye/dotbot) lager symlinkene definert i
`install.conf.yaml`. Kjør `./install` på nytt etter endringer i den filen.

## Struktur

- `zshenv.zsh` - setter `ZDOTDIR` til `~/.config/zsh`
- `zsh/zshrc.zsh` - hoved-zshrc, sourcer filene under i rekkefølge
- `zsh/settings.zsh` - generelle zsh-innstillinger og historikk
- `zsh/lib/` - completion, keybindings, farger, directory-aliaser
- `zsh/zgen.zsh` - plugins via [zgenom](https://github.com/jandamm/zgenom)
- `zsh/aliases.zsh` - aliaser og funksjoner
- `zsh/plugins_after.zsh` - starship, zoxide, fzf, direnv
- `shell/bootstrap.sh` - PATH og editor
- `gitconfig`, `gitignore_global`, `editorconfig`, `starship.toml`, `micro/`

## Lokale tilpasninger

Disse filene leses hvis de finnes, og ligger utenfor repoet:

- `~/.zshrc_local_before` og `~/.zshrc_local_after`
- `~/.zgen_local` - ekstra zgenom-plugins
- `~/.gitconfig_local` - f.eks. jobb-identitet
- `~/.secrets` - API-nøkler og lignende

## Feilsøking av treg oppstart

Sett `export ZSH_DEBUG=true` i `zshenv.zsh`, åpne et nytt shell, og kjør
`zsh/debug/sort_timings.zsh zsh_profile.*` på loggfilen som lages.
