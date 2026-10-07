

def _desktop_argv(value: str) -> list[str]:
    """Read an Exec= value back the way desktops do (Desktop Entry spec):
    undo the string escapes, then split: plain words, or double-quoted ones
    in which a backslash escapes " ` $ and \\."""
    import re
    s = re.sub(r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r"}.get(m[1], m[1]),
               value)
    out, i = [], 0
    while i < len(s):
        if s[i] == " ":
            i += 1
            continue
        word = ""
        if s[i] == '"':
            i += 1
            while s[i] != '"':
                if s[i] == "\\" and s[i + 1] in '"`$\\':
                    i += 1
                word += s[i]
                i += 1
            i += 1
        else:
            while i < len(s) and s[i] != " ":
                word += s[i]
                i += 1
        out.append(word.replace("%%", "%"))
    return out


def test_desktop_entries_start_pisi_from_any_folder_and_nothing_else():
    from companion.autostart import desktop_exec
    for path in ("/home/u/PISI.AppImage",
                 "/home/u/Erkam's Apps/$HOME \"x\" `id` 100%\\z/PISI.AppImage"):
        for argv in ([path], ["bash", "-lc", 'sleep 6; exec "$0"', path]):
            assert _desktop_argv(desktop_exec(argv)) == argv
