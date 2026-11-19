# Spotlight-ekskludering av Elixir-byggmapper.
#
# Bakgrunn: mix legger Erlang-appfiler (foo.app) i _build/, og Spotlight typer dem
# som com.apple.application-file. Alfred viser dem da som "apper" i standardsøket
# (floki, flop, …) med ødelagt ikon. Alfred har ett felles søkeomfang for
# standardresultater og filsøk, så eneste rene løsning er å holde _build utenfor
# Spotlight-indeksen. Verken bundle-bit eller .metadata_never_index virker lenger;
# bare Spotlight sin egen personvernliste gjør det – og den krever sudo.
#
# Bruk:  spotlight-exclude-builds            # legger til alle _build under ~/Documents
#        spotlight-exclude-builds ~/Code     # …under en annen rot
# Kjør på nytt når nye prosjekter er opprettet. Ferdig indekserte treff forsvinner
# når mds startes på nytt (skriptet gjør det til slutt).
spotlight-exclude-builds() {
  emulate -L zsh
  setopt err_return pipe_fail
  local root=${1:-$HOME/Documents}
  local plist=/System/Volumes/Data/.Spotlight-V100/VolumeConfiguration.plist
  local -a dirs
  dirs=(${(f)"$(find "$root" -maxdepth 6 -type d -name _build \
                 -not -path '*/deps/*' -not -path '*/node_modules/*' 2>/dev/null)"})
  if (( ${#dirs} == 0 )); then
    print "Fant ingen _build-mapper under $root"
    return 0
  fi
  local existing
  existing=$(sudo defaults read "$plist" Exclusions 2>/dev/null || true)
  local d added=0
  for d in $dirs; do
    if [[ $existing == *"\"$d\""* ]]; then
      print "allerede ekskludert: ${d/#$HOME/~}"
    else
      sudo defaults write "$plist" Exclusions -array-add "$d"
      print "ekskludert:          ${d/#$HOME/~}"
      (( added++ ))
    fi
  done
  if (( added > 0 )); then
    print "Starter Spotlight (mds) på nytt så gamle treff forsvinner …"
    sudo launchctl kickstart -k system/com.apple.metadata.mds
  fi
}
