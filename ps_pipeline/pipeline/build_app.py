"""build_app.py — inject pipeline_output.json into the app template and write the single-file HTML."""
import json, argparse
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument("--json", default="../data/pipeline_output.json")
ap.add_argument("--out", default="../app/Protected_Species_Decision_Support.html")
a = ap.parse_args()
here = Path(__file__).resolve().parent.parent / "app"
data = json.dumps(json.load(open(a.json)), separators=(",", ":")).replace("</", "<\\/")
html = (here/"template_head.html").read_text() + (here/"template_body.html").read_text() + "<script>\n" + (here/"report_module.js").read_text().replace("</","<\\/") + "\n</script>\n" + (here/"template_script.html").read_text()
html = html.replace("/*__DATA__*/", data)
Path(a.out).write_text(html)
print("wrote", a.out, f"{len(html)/1024:.0f} kB")
