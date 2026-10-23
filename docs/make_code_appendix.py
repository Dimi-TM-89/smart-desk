"""
make_code_appendix.py – Put the source code into the report as "Appendix A – Code".

The report must include the code with its comments. Copying it by hand goes
out of date after every change, so this script generates the appendix straight
from the repository:

  - finds the paragraph "Appendix A – Code" (Heading 1) in the report and
    replaces everything from there to the end of the document;
  - if there is no appendix yet, it is added at the end;
  - every file gets a Heading 2 ("A.3 pi/desk_controller.py") followed by its
    code in Consolas 7.5 pt on a light background, comments in grey italics and
    strings/docstrings in blue, so the comments stand out.

Only the standard library is used (a .docx is a zip file with XML inside).
The rest of the report is not touched, so it can still be edited in Word.

Usage (from the repository root, close the report in Word first):
    python docs/make_code_appendix.py                       # update the report in place
    python docs/make_code_appendix.py -o report-test.docx   # write a copy instead
"""

import argparse
import io
import re
import tokenize
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
REPORT = REPO / "docs" / "Smart Desk - IoT project.docx"
GITHUB = "https://github.com/Dimi-TM-89/smart-desk"

# Files in the appendix, in reading order: configuration, the main program and
# its parts, the other programs, the Pico, the database and the services.
# Not included (see the repository): __init__.py, check_setup.py, pi/tests/, scripts/
FILES = [
    "pi/config.py",
    "pi/desk_controller.py",
    "pi/hardware.py",
    "pi/sensors/ultrasonic.py",
    "pi/sensors/ultrasonic_watcher.py",
    "pi/sensors/light.py",
    "pi/sensors/temperature.py",
    "pi/sensors/adc.py",
    "pi/sensors/button.py",
    "pi/actuators/hw_pwm.py",
    "pi/actuators/lamp.py",
    "pi/actuators/fan.py",
    "pi/actuators/rgb_led.py",
    "pi/actuators/shade.py",
    "pi/actuators/shade_mover.py",
    "pi/actuators/oled.py",
    "pi/posture_ai.py",
    "pi/cloud_bridge.py",
    "pi/db_logger.py",
    "pi/database.py",
    "pi/db_report.py",
    "pico/code.py",
    "db/schema.sql",
    "config/mosquitto/smartdesk.conf",
    "systemd/smartdesk.target",
    "systemd/smartdesk-controller.service",
    "systemd/smartdesk-posture.service",
    "systemd/smartdesk-cloud.service",
    "systemd/smartdesk-db.service",
]

TITLE = "Appendix A – Code"

# Look of the report (same fonts and colours as the tables in the report)
CODE_FONT = "Consolas"
CODE_SIZE = 15                 # half-points: 7.5 pt fits 116 characters on one line
CODE_BACKGROUND = "F5F8F6"     # the light green-grey of the table rows
COLOURS = {"code": "1F2A30", "comment": "6B7780", "string": "2B4C7E"}


# ---------------------------------------------------------------------------
# Colouring: which characters of a line are code, comment or string
# ---------------------------------------------------------------------------
def python_kinds(lines):
    """Return per line a list with the kind of every character, using Python's tokenizer."""
    kinds = [["code"] * len(line) for line in lines]
    source = "\n".join(lines) + "\n"
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return kinds                          # cannot tokenize: no colours, still correct text
    for tok in tokens:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        kind = "comment" if tok.type == tokenize.COMMENT else "string"
        (r1, c1), (r2, c2) = tok.start, tok.end
        for row in range(r1, r2 + 1):
            if row - 1 >= len(lines):
                break
            start = c1 if row == r1 else 0
            end = c2 if row == r2 else len(lines[row - 1])
            for col in range(start, min(end, len(lines[row - 1]))):
                kinds[row - 1][col] = kind
    return kinds


def line_comment_kinds(lines, marker):
    """Simple colouring for SQL and config files: a line starting with the marker is a comment."""
    kinds = []
    for line in lines:
        if line.lstrip().startswith(marker):
            kinds.append(["comment"] * len(line))
        else:
            kinds.append(["code"] * len(line))
    return kinds


def segments(line, kinds):
    """Split a line into (text, kind) pieces with the same kind."""
    out = []
    for char, kind in zip(line, kinds):
        if out and out[-1][1] == kind:
            out[-1][0] += char
        else:
            out.append([char, kind])
    return out


# ---------------------------------------------------------------------------
# WordprocessingML pieces
# ---------------------------------------------------------------------------
def run(text, kind="code"):
    """One run of code text in the code font."""
    italic = "<w:i/><w:iCs/>" if kind == "comment" else ""
    return (f'<w:r><w:rPr><w:rFonts w:ascii="{CODE_FONT}" w:cs="{CODE_FONT}" '
            f'w:eastAsia="{CODE_FONT}" w:hAnsi="{CODE_FONT}"/>{italic}'
            f'<w:color w:val="{COLOURS[kind]}"/><w:sz w:val="{CODE_SIZE}"/>'
            f'<w:szCs w:val="{CODE_SIZE}"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def code_paragraph(pieces):
    """One line of code: a paragraph with background and no spacing (empty lines keep their height)."""
    p_pr = (f'<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="{CODE_BACKGROUND}"/>'
            f'<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
            f'<w:rPr><w:rFonts w:ascii="{CODE_FONT}" w:hAnsi="{CODE_FONT}"/>'
            f'<w:sz w:val="{CODE_SIZE}"/><w:szCs w:val="{CODE_SIZE}"/></w:rPr></w:pPr>')
    return f"<w:p>{p_pr}{''.join(run(t, k) for t, k in pieces)}</w:p>"


def arial_run(text, bold=False, italic=False, colour=None, code=False):
    """A run in the report's body font (or the inline code style of the report)."""
    if code:
        return (f'<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:cs="Consolas" w:eastAsia="Consolas" '
                f'w:hAnsi="Consolas"/><w:color w:val="2B4C7E"/><w:sz w:val="19"/><w:szCs w:val="19"/>'
                f'</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>')
    props = '<w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>'
    props += "<w:b/><w:bCs/>" if bold else ""
    props += "<w:i/><w:iCs/>" if italic else ""
    props += f'<w:color w:val="{colour}"/>' if colour else ""
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def heading(text, level, page_break=False):
    """Heading 1 / Heading 2 paragraph, like the other headings in the report."""
    brk = "<w:pageBreakBefore/>" if page_break else ""
    keep = "<w:keepNext/>" if level == 2 else ""
    return (f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/>{keep}{brk}</w:pPr>'
            f"{arial_run(text)}</w:p>")


def body(*runs, after=120):
    """Body paragraph in the report's spacing."""
    return f'<w:p><w:pPr><w:spacing w:after="{after}" w:line="276"/></w:pPr>{"".join(runs)}</w:p>'


def file_block(number, rel_path):
    """Heading plus all code lines of one file."""
    text = (REPO / rel_path).read_text(encoding="utf-8").expandtabs(4)
    lines = text.rstrip("\n").split("\n")
    if rel_path.endswith(".py"):
        kinds = python_kinds(lines)
    elif rel_path.endswith(".sql"):
        kinds = line_comment_kinds(lines, "--")
    else:
        kinds = line_comment_kinds(lines, "#")
    xml = [heading(f"A.{number} {rel_path}  ({len(lines)} lines)", 2)]
    xml += [code_paragraph(segments(line, k)) for line, k in zip(lines, kinds)]
    xml.append(body(after=160))
    return "".join(xml)


def build_appendix():
    """The complete appendix as WordprocessingML, and the number of code lines."""
    total = sum(len((REPO / f).read_text(encoding="utf-8").rstrip("\n").split("\n")) for f in FILES)
    xml = [heading(TITLE, 1, page_break=True)]
    xml.append(body(
        arial_run("This appendix is generated from the repository with "),
        arial_run("docs/make_code_appendix.py", code=True),
        arial_run(f" ({len(FILES)} files, {total} lines). Every file starts with a header comment "
                  "that explains its job, every class and function has a docstring, and inline "
                  "comments explain the less obvious steps. Comments are shown in "),
        arial_run("grey italics", italic=True, colour=COLOURS["comment"]),
        arial_run(", strings and docstrings in "),
        arial_run("blue", colour=COLOURS["string"]),
        arial_run("."),
    ))
    xml.append(body(
        arial_run("Repository: "), arial_run(GITHUB, code=True),
        arial_run(". Only there: the setup scripts ("), arial_run("scripts/", code=True),
        arial_run("), the component tests and the desk simulator ("), arial_run("pi/tests/", code=True),
        arial_run("), "), arial_run("check_setup.py", code=True), arial_run(" and the README."),
    ))
    for number, rel_path in enumerate(FILES, start=1):
        xml.append(file_block(number, rel_path))
    return "".join(xml), total


# ---------------------------------------------------------------------------
# Putting it into the report
# ---------------------------------------------------------------------------
def insert_appendix(document_xml, appendix_xml):
    """Replace the existing appendix (or add one) just before the final section properties."""
    body_end = document_xml.rfind("<w:sectPr")
    if body_end < 0 or document_xml.find("</w:body>", body_end) < 0:
        raise RuntimeError("unexpected document.xml: no final <w:sectPr> in the body")

    start = None
    for match in re.finditer(r"<w:p[ >].*?</w:p>", document_xml[:body_end], flags=re.S):
        para = match.group(0)
        if 'w:val="Heading1"' in para and re.sub(r"<[^>]+>", "", para).strip().startswith("Appendix A"):
            start = match.start()
            break
    if start is None:
        start = body_end                     # no appendix yet: add it at the end
    return document_xml[:start] + appendix_xml + document_xml[body_end:]


def main():
    """Read the report, rebuild the appendix and write the result."""
    parser = argparse.ArgumentParser(description="Generate 'Appendix A – Code' in the Smart Desk report")
    parser.add_argument("report", nargs="?", default=str(REPORT), help="report .docx (default: docs/…)")
    parser.add_argument("-o", "--output", help="write here instead of updating the report in place")
    args = parser.parse_args()

    source = Path(args.report)
    target = Path(args.output) if args.output else source
    appendix, total = build_appendix()

    with zipfile.ZipFile(source) as zin:
        entries = [(info, zin.read(info.filename)) for info in zin.infolist()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in entries:
            if info.filename == "word/document.xml":
                data = insert_appendix(data.decode("utf-8"), appendix).encode("utf-8")
            zout.writestr(info, data)
    target.write_bytes(buffer.getvalue())     # written only after everything succeeded
    print(f"{target}: appendix with {len(FILES)} files, {total} lines of code")


if __name__ == "__main__":
    main()
