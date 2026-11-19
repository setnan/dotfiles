"""Sublime Text-plugin: åpne bestemte .txt-filer med Markdown-syntaks.

Brukes for sammendragsfila fra Alfred (`sum` → sum.txt), som skrives som
Markdown men skal hete .txt. Filnavnene settes i Preferences.sublime-settings:

    "txt_as_markdown": ["sum.txt"]

Matcher på filnavn (ikke sti), så alle filer med det navnet får Markdown.
"""
import os

import sublime
import sublime_plugin

MARKDOWN = "Packages/Markdown/Markdown.sublime-syntax"


def _wanted(view):
    name = view.file_name()
    if not name:
        return False
    names = sublime.load_settings("Preferences.sublime-settings").get("txt_as_markdown", [])
    return os.path.basename(name) in names


def _apply(view):
    if _wanted(view) and view.settings().get("syntax") != MARKDOWN:
        view.assign_syntax(MARKDOWN)


class TxtAsMarkdown(sublime_plugin.EventListener):
    def on_load(self, view):
        _apply(view)

    def on_activated(self, view):
        _apply(view)

    def on_post_save(self, view):
        _apply(view)
