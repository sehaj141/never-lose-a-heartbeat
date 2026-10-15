"""
Convert Markdown documentation to clean, publication-ready PDFs using headless Edge.
Ensures seamless 1-click preview in Google Drive and PDF readers.
"""

import os
import subprocess
import html
import re

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def md_to_simple_html(md_text: str, title: str) -> str:
    # Basic markdown to HTML converter with clean styling
    lines = md_text.split("\n")
    html_lines = []
    in_code_block = False
    in_table = False

    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.5; color: #24292e; max-width: 850px; margin: 40px auto; padding: 0 30px; font-size: 13.5px; }
        h1 { border-bottom: 2px solid #eaecef; padding-bottom: 0.3em; font-size: 22px; color: #0366d6; margin-top: 0; }
        h2 { border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; font-size: 17px; margin-top: 24px; color: #24292e; }
        h3 { font-size: 15px; margin-top: 20px; }
        table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 12.5px; }
        table th, table td { border: 1px solid #dfe2e5; padding: 6px 10px; text-align: left; }
        table th { background-color: #f6f8fa; font-weight: 600; }
        table tr:nth-child(2n) { background-color: #fafbfc; }
        code { background-color: rgba(27,31,35,0.05); padding: 0.2em 0.4em; border-radius: 3px; font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; font-size: 85%; }
        pre { background-color: #f6f8fa; border-radius: 6px; padding: 12px; overflow: auto; font-size: 12px; border: 1px solid #e1e4e8; }
        pre code { background: none; padding: 0; }
        blockquote { border-left: 4px solid #dfe2e5; color: #6a737d; padding: 0 1em; margin: 0; }
        hr { border: 0; height: 1px; background: #e1e4e8; margin: 20px 0; }
        .badge { background: #28a745; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    </style>
    """

    for line in lines:
        if line.startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                html_lines.append("<pre><code>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(html.escape(line))
            continue

        stripped = line.strip()

        # Tables
        if "|" in stripped and not stripped.startswith("#"):
            if not in_table:
                html_lines.append("<table>")
                in_table = True
            if re.match(r"^\|?[\s\-:]+\|[\s\-:]+\|?", stripped):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            tag = "th" if ("Status" in stripped or "Metric" in stripped or "Criterion" in stripped or "Guarantee" in stripped or "Deliverable" in stripped) else "td"
            row_html = "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
            html_lines.append(row_html)
            continue
        else:
            if in_table:
                html_lines.append("</table>")
                in_table = False

        if not stripped:
            html_lines.append("<br>")
            continue

        if stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("---"):
            html_lines.append("<hr>")
        elif stripped.startswith("* ") or stripped.startswith("- "):
            html_lines.append(f"<li>{stripped[2:]}</li>")
        else:
            # Inline formatting
            formatted = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", stripped)
            formatted = re.sub(r"`(.*?)`", r"<code>\1</code>", formatted)
            html_lines.append(f"<p>{formatted}</p>")

    if in_table:
        html_lines.append("</table>")

    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title>{css}</head><body>" + "\n".join(html_lines) + "</body></html>"


def convert_file(md_path: str, pdf_path: str):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    title = os.path.basename(md_path)
    html_content = md_to_simple_html(md_text, title)
    temp_html = pdf_path.replace(".pdf", ".html")
    with open(temp_html, "w", encoding="utf-8") as f:
        f.write(html_content)

    cmd = [
        EDGE_EXE,
        "--headless",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        temp_html
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(temp_html):
        os.remove(temp_html)
    print(f"Created PDF: {pdf_path}")


if __name__ == "__main__":
    docs = [
        "DESIGN_NOTE.md",
        "DELIVERABLE_3_FAILURE_TEST_EVIDENCE.md",
        "DELIVERABLE_4_RESOURCE_PROFILE.md",
        "DELIVERABLE_5_DEMO_VIDEO_GUIDE.md"
    ]
    for doc in docs:
        full_md = os.path.join(PROJECT_DIR, doc)
        full_pdf = os.path.join(PROJECT_DIR, doc.replace(".md", ".pdf"))
        if os.path.exists(full_md):
            convert_file(full_md, full_pdf)
