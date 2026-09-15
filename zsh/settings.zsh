# General zsh settings

# Completion must be initialized before plugins that call compdef
autoload -Uz compinit
compinit -d "${XDG_CACHE_HOME:-$HOME/.cache}/zsh/zcompdump"

# Enable interactive comments (# on the command line)
setopt interactivecomments

## History file configuration
# Explicit path: macOS /etc/zshrc would otherwise put it inside $ZDOTDIR
HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=$HISTSIZE

## History command configuration
setopt extended_history       # record timestamp of command in HISTFILE
setopt hist_expire_dups_first # delete duplicates first when HISTFILE size exceeds HISTSIZE
setopt hist_ignore_dups       # ignore duplicated commands history list
setopt hist_ignore_space      # ignore commands that start with space
setopt hist_verify            # show command with history expansion to user before running it
setopt inc_append_history     # add commands to HISTFILE in order of execution
setopt share_history          # share command history data

#
# Set environment variable "$1" to default value "$2" if "$1" is not yet defined.
#
function env_default() {
    env | grep -q "^$1=" && return 0
    export "$1=$2"       && return 3
}

env_default 'PAGER' 'less'
env_default 'LESS' '-R'
