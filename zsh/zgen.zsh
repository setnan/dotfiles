# load zgenom
source "${HOME}/.zgenom/zgenom.zsh"

# Check for plugin and zgenom updates every 7 days
zgenom autoupdate

# if the init script doesn't exist
if ! zgenom saved; then
    echo "Creating a zgenom save"

    # oh-my-zsh plugins
    zgenom ohmyzsh plugins/git
    zgenom ohmyzsh plugins/docker
    zgenom ohmyzsh plugins/docker-compose
    zgenom ohmyzsh plugins/mix

    # plugins
    zgenom load zsh-users/zsh-autosuggestions
    zgenom load zdharma-continuum/fast-syntax-highlighting
    zgenom load mroth/evalcache

    # completions
    zgenom load zsh-users/zsh-completions src

    # Add or override plugins locally
    if [ -f ~/.zgen_local ]; then
        source ~/.zgen_local
    fi

    # save all to init script (runs compinit)
    zgenom save

    zgenom compile $ZDOTDIR
fi
