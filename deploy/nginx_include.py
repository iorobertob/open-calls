#!/usr/bin/env python3
"""Add `include <snippet>;` to the HTTPS server block(s) of a domain in an nginx site file.

    python3 nginx_include.py <site-file> <domain> <snippet>     # prints the new file to stdout

Only server blocks that both name the domain in `server_name` and `listen ... 443` are changed
(the port-80 certbot redirect block is left alone). The include goes right after `server_name`,
the same place as other app snippets (e.g. lmta-museum.conf). Comments are ignored when parsing.
Exit code 3 if no matching block was found. Idempotency is checked by the caller (grep)."""
import re
import sys


def strip_comment(line):
    out, quote = [], None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out)


def main(path, domain, snippet):
    lines = open(path, encoding="utf-8").read().split("\n")
    depth, block_start, blocks = 0, None, []
    for i, raw in enumerate(lines):
        code = strip_comment(raw)
        if depth == 0 and re.match(r"\s*server\s*(\{|$)", code):
            block_start = i
        depth += code.count("{") - code.count("}")
        if block_start is not None and depth == 0 and "}" in code:
            blocks.append((block_start, i))
            block_start = None

    inserts = []
    for start, end in blocks:
        body = [strip_comment(l) for l in lines[start:end + 1]]
        listens_443 = any(re.search(r"^\s*listen\s+[^;]*\b443\b", l) for l in body)
        name_line = next((start + k for k, l in enumerate(body)
                          if re.search(r"^\s*server_name\s[^;]*(?<![\w.-])" + re.escape(domain) + r"(?![\w.-])", l)),
                         None)
        if listens_443 and name_line is not None:
            indent = re.match(r"\s*", lines[name_line]).group(0)
            inserts.append((name_line, f"{indent}include {snippet};  # MISC open calls"))
    if not inserts:
        sys.exit(3)
    for idx, text in sorted(inserts, reverse=True):
        lines.insert(idx + 1, text)
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main(*sys.argv[1:4])
