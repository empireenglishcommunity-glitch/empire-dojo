#!/usr/bin/env python3
"""Build a single A/B/C listening-test page.

The owner hears the SAME 20 sentences rendered three ways — Kokoro, their voice
via F5-TTS, their voice via Chatterbox — side by side, and picks. One link, no
Discord spam, no 60 separate files to open. Uploaded to R2 under an unguessable
prefix and deleted after the decision.

Usage: build_compare_page.py <clips_dir> <out_html> <public_base_url>
  clips_dir must contain {id}.{engine}.mp3 for engine in kokoro/f5/chatterbox.
"""
import json
import sys
from pathlib import Path

ENGINES = [("kokoro", "Kokoro (native voice)"),
           ("f5", "Your voice — F5-TTS"),
           ("chatterbox", "Your voice — Chatterbox")]


def main():
    clips_dir, out_html, base = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].rstrip("/")
    sents = json.loads(
        (Path(__file__).parent / "listening_test_sentences.json").read_text(
            encoding="utf-8"))["sentences"]

    rows = []
    for s in sents:
        cells = []
        for eng, label in ENGINES:
            fn = f"{s['id']}.{eng}.mp3"
            exists = (clips_dir / fn).exists()
            if exists:
                cells.append(
                    f'<td><div class="eng">{label}</div>'
                    f'<audio controls preload="none" src="{base}/{fn}"></audio></td>')
            else:
                cells.append(f'<td><div class="eng">{label}</div>'
                             f'<span class="miss">— not rendered —</span></td>')
        rows.append(
            f'<tr><td class="txt"><span class="sid">{s["id"]}</span>'
            f'<span class="surf">{s["surface"]}</span>'
            f'<div>{s["text"]}</div></td>{"".join(cells)}</tr>')

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice Listening Test — Empire English</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e8e8e8;margin:0;padding:20px;line-height:1.5}}
 h1{{color:#d4af37}} .sub{{color:#9aa;margin-bottom:20px;max-width:760px}}
 table{{border-collapse:collapse;width:100%;max-width:1100px}}
 td{{border:1px solid #2a2d34;padding:10px;vertical-align:top}}
 .txt{{width:34%;font-size:0.95rem}} .sid{{color:#d4af37;font-weight:600;margin-right:8px}}
 .surf{{color:#7a8;font-size:0.75rem;text-transform:uppercase;border:1px solid #2a4;border-radius:4px;padding:1px 6px}}
 .eng{{font-size:0.8rem;color:#9aa;margin-bottom:6px}} audio{{width:230px;max-width:100%}}
 .miss{{color:#a55;font-size:0.85rem}}
 thead td{{background:#191c22;color:#d4af37;font-weight:600;position:sticky;top:0}}
</style></head><body>
<h1>🎧 Voice Listening Test</h1>
<div class="sub">Same 20 sentences, three engines. Play across each row and compare.
Decide per surface — for example your voice for teaching/encouragement, and the
native voice for the accent drill. Nothing is committed to the site until you choose.</div>
<table><thead><tr><td>Sentence</td><td>Kokoro</td><td>Your voice (F5)</td><td>Your voice (Chatterbox)</td></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p class="sub" style="margin-top:24px">Reply with: which engine for your voice, and confirm the accent drill stays native. This page is temporary and will be removed.</p>
</body></html>"""
    out_html.write_text(html, encoding="utf-8")
    print(f"  wrote {out_html} ({len(sents)} sentences x {len(ENGINES)} engines)")


if __name__ == "__main__":
    main()
