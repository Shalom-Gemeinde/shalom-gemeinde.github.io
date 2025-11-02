#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: this script requires PyYAML. Install it with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


PLACEHOLDER_RE = re.compile(r"%([A-Za-z0-9_\-]+)%")

# Common key corrections for typos
KEY_ALIASES = {
    "brief-ptrb": "brief-ptbr",
    "titel-de": "title-de",
}


def load_yaml(path: Path) -> dict:
    """Load and parse YAML safely."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or {}
    except yaml.YAMLError as e:
        print(f"Error parsing YAML '{path}': {e}", file=sys.stderr)
        sys.exit(1)


def sanitize_node(node: dict) -> dict:
    """Normalize node keys and fix known typos."""
    if not isinstance(node, dict):
        return {}
    node = dict(node)
    for wrong, right in KEY_ALIASES.items():
        if wrong in node and right not in node:
            node[right] = node.pop(wrong)
    return node


def render_template(template: str, context: dict, *, strict: bool = False) -> str:
    """Replace %key% placeholders using the given context dictionary."""

    def repl(match):
        key = match.group(1)
        if key in context and context[key] is not None:
            return str(context[key])
        if strict:
            raise KeyError(f"Placeholder '%{key}%' not found in node.")
        print(f"[warning] Placeholder '%{key}%' has no value; replaced with empty string.", file=sys.stderr)
        return ""

    return PLACEHOLDER_RE.sub(repl, template)


def ensure_parent_dir(path: Path, *, dry_run: bool):
    """Create parent directories if necessary."""
    parent = path.parent
    if not parent.exists():
        if dry_run:
            print(f"[dry-run] Would create directory: {parent}")
        else:
            parent.mkdir(parents=True, exist_ok=True)


def process(data: dict, out_dir: Path, *, strict: bool, dry_run: bool) -> int:
    """
    Main processing logic for the NEW YAML schema:

    output:
      filename: "src/posts/audio-%date%-predige.md"
      template: |
        {{%title-de%}}
        ###%title-ptbr%

    files:
      - audio: AUDIO-2025-10-16.m4a
        date: 20251016
        title-de: Das titel
        title-ptbr: O Título
        brief-de: |
          ...
        brief-ptbr: |
          ...
    """
    if not isinstance(data, dict):
        print("Error: YAML root must be a mapping object.", file=sys.stderr)
        return 1

    output = data.get("output")
    files = data.get("files")

    if not isinstance(output, dict):
        print("Error: field 'output' missing or not a mapping.", file=sys.stderr)
        return 1

    template = output.get("template")
    filename_tpl = output.get("filename")

    if not isinstance(template, str):
        print("Error: field 'output.template' missing or not a string.", file=sys.stderr)
        return 1
    if not isinstance(filename_tpl, str):
        print("Error: field 'output.filename' missing or not a string.", file=sys.stderr)
        return 1
    if not isinstance(files, list):
        print("Error: field 'files' missing or not a list.", file=sys.stderr)
        return 1

    out_dir = out_dir.resolve()
    if not out_dir.exists():
        if dry_run:
            print(f"[dry-run] Would create output directory: {out_dir}")
        else:
            out_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0

    for idx, raw_node in enumerate(files, 1):
        node = sanitize_node(raw_node)

        if not isinstance(node, dict):
            print(f"[error] files[{idx}] is not a mapping object.", file=sys.stderr)
            exit_code = 1
            continue

        audio_path = node.get("audio")
        if not audio_path or not isinstance(audio_path, str):
            print(f"[error] files[{idx}] missing valid 'audio' field.", file=sys.stderr)
            exit_code = 1
            continue

        # Check if audio file exists
        audio_file = Path(audio_path)
        if not audio_file.exists():
            print(f"[error] Audio file not found: '{audio_file}' (in files[{idx}])", file=sys.stderr)
            exit_code = 1
            continue

        # Context: all string-keyed entries of the node
        context = {k: v for k, v in node.items() if isinstance(k, str)}

        # 1) Render filename from output.filename using placeholders like %date%, %title-de%, etc.
        try:
            rendered_filename = render_template(filename_tpl, context, strict=strict)
        except KeyError as e:
            print(f"[error] {e} while rendering output.filename in files[{idx}]", file=sys.stderr)
            exit_code = 1
            continue

        rendered_filename = rendered_filename.strip()
        if rendered_filename == "":
            print(f"[error] Empty output filename after rendering in files[{idx}].", file=sys.stderr)
            exit_code = 1
            continue

        target = (out_dir / rendered_filename).resolve()

        # 2) Render file content from output.template with the same placeholders
        try:
            content = render_template(template, context, strict=strict)
        except KeyError as e:
            print(f"[error] {e} while rendering template in files[{idx}] → filename='{rendered_filename}'", file=sys.stderr)
            exit_code = 1
            continue

        if target.exists():
            print(f"[ok] File already exists: {target}")
            continue

        ensure_parent_dir(target, dry_run=dry_run)
        if dry_run:
            print(f"[dry-run] Would create file: {target}")
        else:
            with target.open("w", encoding="utf-8", newline="\n") as f:
                f.write(content.rstrip() + "\n")
            print(f"[new] Created: {target}")

    return exit_code


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate files from a YAML with 'output.filename', 'output.template' and 'files'. "
            "Both template and filename support %placeholders% taken from each node in 'files'."
        )
    )
    parser.add_argument("yaml_path", type=Path, help="Path to input YAML file.")
    parser.add_argument(
        "-o", "--out-dir", type=Path, default=Path("."),
        help="Base directory for generated files (default: current directory)."
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Fail if any placeholder (in filename or template) is missing in a node."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Do not write files; only print what would be done."
    )
    args = parser.parse_args()

    data = load_yaml(args.yaml_path)
    rc = process(data, args.out_dir, strict=args.strict, dry_run=args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
