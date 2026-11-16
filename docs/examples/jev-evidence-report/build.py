"""Insert report data JSON into template.html, writing a self-contained index.html.

Usage: python3 build.py report-data.json [template.html] [index.html]
"""
import sys
from pathlib import Path

here = Path(__file__).parent
data = Path(sys.argv[1]).read_text().replace("</", "<\\/")
template = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "template.html"
out = Path(sys.argv[3]) if len(sys.argv) > 3 else here / "index.html"
html = template.read_text()
assert "/*DATA*/null" in html, "template is missing the /*DATA*/null placeholder"
out.write_text(html.replace("/*DATA*/null", data))
print(f"wrote {out} ({out.stat().st_size} bytes)")
