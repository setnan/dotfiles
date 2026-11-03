#!/usr/bin/env python3
"""Alfred Script Filter: lorem ipsum med nøyaktig N tegn, klar til utklippstavlen.

`lorem 250` → ett valg som legger 250 tegn på utklippstavlen. Uten tall brukes
DEFAULT. Teksten bygges ord for ord fra den klassiske lorem ipsum-passasjen og
avsluttes med punktum; de siste ordene velges slik at lengden treffer N eksakt,
så ingen ord kuttes midt i. Alfred får teksten som `arg` og antallet som
variabelen `count` (til varselet).
"""
import json
import sys

DEFAULT = 250
MAX = 100_000

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud "
    "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure "
    "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum. Curabitur pretium tincidunt lacus, nulla gravida orci a "
    "odio. Nullam varius, turpis et commodo pharetra, est eros bibendum elit, nec luctus "
    "magna felis sollicitudin mauris. Integer in mauris eu nibh euismod gravida. Duis ac "
    "tellus et risus vulputate vehicula. Donec lobortis risus a elit. Etiam tempor. Ut "
    "ullamcorper, ligula eu tempor congue, eros est euismod turpis, id tincidunt sapien "
    "risus a quam. Maecenas fermentum consequat mi. Donec fermentum. Pellentesque malesuada "
    "nulla a mi. Duis sapien sem, aliquet nec, commodo eget, consequat quis, neque. Aliquam "
    "faucibus, elit ut dictum aliquet, felis nisl adipiscing sapien, sed malesuada diam "
    "lacus eget erat. Cras mollis scelerisque nunc. Nullam arcu. Aliquam consequat. "
    "Curabitur augue lorem, dapibus quis, laoreet et, pretium ac, nisi. Aenean magna nisl, "
    "mollis quis, molestie eu, feugiat in, orci. In hac habitasse platea dictumst."
)
WORDS = LOREM.split()
# Rene ord (små bokstaver, uten tegnsetting) gruppert på lengde, 1–13 tegn.
BY_LEN = {}
for _w in WORDS:
    _c = _w.strip(".,").lower()
    if _c not in BY_LEN.setdefault(len(_c), []):
        BY_LEN[len(_c)].append(_c)
MAX_WORD = max(BY_LEN)


def fill(k, seed):
    """Ord (skilt med mellomrom) som til sammen er nøyaktig k tegn, k >= 1."""
    if k <= MAX_WORD:
        choices = BY_LEN[k]
        return choices[seed % len(choices)]
    head = BY_LEN[6][seed % len(BY_LEN[6])]
    return head + " " + fill(k - 7, seed + 1)


def lorem(n):
    if n <= 0:
        return ""
    if n < 6:
        return "Lorem ipsum"[:n]
    out, length, i = [], 0, 0
    while True:
        w = WORDS[i % len(WORDS)]
        add = len(w) + (1 if out else 0)
        if length + add + 1 > n:  # +1: punktum til slutt
            break
        out.append(w)
        length += add
        i += 1
    out[-1] = out[-1].rstrip(".,")
    need = n - 1 - len(" ".join(out))  # tegn som mangler før punktum
    # need == 1 gir ikke plass til mellomrom + ord, og need == 2 gir bare et
    # énbokstavsord; fjern da siste ord og fyll opp med lengre ord i stedet.
    while out and need in (1, 2):
        out.pop()
        need = n - 1 - len(" ".join(out))
    if need > 0:
        out.append(fill(need - 1 if out else need, i))
    text = " ".join(out) + "."
    return text[0].upper() + text[1:]


def parse(query):
    q = query.strip().lower().replace("tegn", "").strip()
    if not q:
        return DEFAULT, None
    try:
        n = int(q)
    except ValueError:
        return None, f"Skjønte ikke «{query.strip()}» – skriv et antall tegn"
    if n < 1:
        return None, "Antall må være minst 1"
    return min(n, MAX), None


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    n, err = parse(query)
    if err:
        item = {"title": err, "subtitle": "F.eks. «lorem 250» eller «lorem 1000»", "valid": False}
    else:
        text = lorem(n)
        preview = text[:90] + ("…" if len(text) > 90 else "")
        item = {
            "uid": "lorem",
            "title": f"Kopier {n} tegn lorem ipsum",
            "subtitle": preview,
            "arg": text,
            "text": {"copy": text, "largetype": text},
            "variables": {"count": str(n)},
        }
    json.dump({"items": [item]}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
