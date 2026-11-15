#!/usr/bin/env python3
"""Type text into a libvirt VM's keyboard (US layout), then press Enter.
Usage: vm-type.py VM "text to type" | @file     (one virsh connection, so one auth prompt)"""
import subprocess, sys

vm, text = sys.argv[1], sys.argv[2]
if text.startswith("@"): text = open(text[1:]).read().strip()  # @file: type the file's contents
plain = {**{c: f"KEY_{c.upper()}" for c in "abcdefghijklmnopqrstuvwxyz"}, **{d: f"KEY_{d}" for d in "0123456789"},
         " ": "KEY_SPACE", "-": "KEY_MINUS", "=": "KEY_EQUAL", ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE",
         ",": "KEY_COMMA", ".": "KEY_DOT", "/": "KEY_SLASH", "\\": "KEY_BACKSLASH", "`": "KEY_GRAVE",
         "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE"}
shifted = {"~": "KEY_GRAVE", "_": "KEY_MINUS", "+": "KEY_EQUAL", ":": "KEY_SEMICOLON", '"': "KEY_APOSTROPHE",
           "<": "KEY_COMMA", ">": "KEY_DOT", "?": "KEY_SLASH", "|": "KEY_BACKSLASH", "{": "KEY_LEFTBRACE", "}": "KEY_RIGHTBRACE",
           **{s: f"KEY_{d}" for s, d in zip("!@#$%^&*()", "1234567890")}}
cmds = []
for ch in text:
    if ch in plain: cmds.append(f"send-key {vm} {plain[ch]}")
    elif ch.isupper(): cmds.append(f"send-key {vm} KEY_LEFTSHIFT KEY_{ch}")
    elif ch in shifted: cmds.append(f"send-key {vm} KEY_LEFTSHIFT {shifted[ch]}")
    else: sys.exit(f"can't type {ch!r}")
cmds.append(f"send-key {vm} KEY_ENTER")
# Send in small chunks with pauses: a long burst makes the guest drop keys.
import time
for i in range(0, len(cmds), 12):
    r = subprocess.run(["virsh", "-c", "qemu:///system"], input="\n".join(cmds[i:i + 12]) + "\n", text=True, capture_output=True)
    if r.returncode != 0: sys.exit(r.stderr.strip())
    time.sleep(0.15)
print(f"typed {len(text)} characters")
