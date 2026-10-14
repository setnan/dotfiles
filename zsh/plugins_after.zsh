# External plugins (initialized after)

# Prompt
_evalcache starship init zsh

# zoxide (smart cd): z <dir>, zi for interactive
if (( $+commands[zoxide] )); then
  # fzf-utseende for zi: tre-forhåndsvisning med eza til høyre, poengkolonnen skjult
  export _ZO_FZF_OPTS="
    --exact --no-sort --cycle --keep-right --exit-0 --select-1
    --bind=ctrl-z:ignore,btab:up,tab:down
    --height=60% --layout=reverse --border=rounded --info=inline --tabstop=1
    --with-nth=2.. --prompt='cd ❯ ' --header='enter: gå til · esc: avbryt'
    --preview-window=right,55%,border-left
    --preview='eza --tree --level=1 --icons=always --color=always --group-directories-first {2..}'
  "
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
