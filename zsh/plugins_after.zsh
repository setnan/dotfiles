# External plugins (initialized after)

# Prompt
_evalcache starship init zsh

# zoxide (smart cd): z <dir>, zi for interactive
if (( $+commands[zoxide] )); then
  _evalcache zoxide init zsh
  alias j=z
fi

# fzf keybindings and completion (Ctrl-R history, Ctrl-T files, Alt-C cd)
if (( $+commands[fzf] )); then
  source <(fzf --zsh)
fi

# direnv
if (( $+commands[direnv] )); then
  _evalcache direnv hook zsh
fi

# bun completions
[ -s "$HOME/.bun/_bun" ] && source "$HOME/.bun/_bun"
