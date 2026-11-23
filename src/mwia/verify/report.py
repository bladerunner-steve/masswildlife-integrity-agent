"""Integrity badge and report pages.

badge.svg   self-contained SVG: green (VERIFIED WITHIN SCOPE), red (VERIFICATION FAILED), amber (INSUFFICIENT
            EVIDENCE), labelled with the configuration that produced it
index.html  per run (Jinja2, no external requests): status, plain-language explanation, scope statement,
            window, counts, a PR0-PR5 table with a mark per layer, the localized failure, findings, and a
            "token needs refresh" banner when applicable
reports/index.html  every verified run, newest first, with its badge
Wording is aimed at readers who are not cryptographers. The scope statement always says what the badge does
NOT attest (factual correctness of the observations).
AI-assisted (Claude). Verified by: tests/test_verify.py (badge colours/labels, page content, no external URLs).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .engine import FAILED, INSUFFICIENT, VERIFIED

TEMPLATES = Path(__file__).resolve().parents[3] / "templates"
COLOURS = {VERIFIED: "#1e7b34", FAILED: "#b3261e", INSUFFICIENT: "#b26a00"}
LAYER_NAMES = {"A": "cryptographic", "B": "policy", "C": "evidence"}

EXPLAIN = {
    VERIFIED: {
        "A": "The receipts are authentic and unaltered. Only the cryptographic layer was checked: this configuration "
             "does not check whether the run followed policy or whether its evidence is complete.",
        "B": "The receipts are authentic and unaltered, and the run followed its signed plan and the policy. The "
             "completeness of the evidence was not checked in this configuration.",
        "C": "The receipts are authentic and unaltered, the run followed its signed plan and the policy, and every "
             "required piece of evidence is present and adds up.",
    },
    FAILED: "Something in this run's record is wrong, so do not rely on this run. See the first problem below.",
    INSUFFICIENT: "Nothing was found to be altered or against policy, but required evidence is missing, stale or does "
                  "not add up, so this run cannot be fully vouched for.",
}


def scope_statement(config: str) -> str:
    checked = {"A": "untampered", "B": "untampered, plan-conformant and policy-compliant",
               "C": "untampered, plan-conformant and policy-compliant, with sufficient recorded evidence"}[config]
    return (f"Scope: this badge attests that the run was {checked}. It does not attest that the observations "
            f"themselves are factually correct (for example, species identifications or locations), and it says "
            f"nothing about the reasoning of the people or software that produced them.")


def badge_svg(status: str, config: str) -> str:
    left, right = "integrity", status
    lw, rw = 62, int(len(right) * 7.0) + 20
    w = lw + rw
    colour = COLOURS[status]
    title = html.escape(f"Integrity: {status} (verifier configuration {config})")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="22" role="img" aria-label="{title}">'
            f'<title>{title}</title>'
            f'<rect width="{lw}" height="22" fill="#444"/><rect x="{lw}" width="{rw}" height="22" fill="{colour}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,Arial,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{lw / 2}" y="15">{left}</text><text x="{lw + rw / 2}" y="15" font-weight="bold">'
            f'{html.escape(right)}</text></g></svg>')


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))


def explanation(v: dict) -> str:
    e = EXPLAIN[v["status"]]
    return e[v["config"]] if isinstance(e, dict) else e


def write_run_report(verdict: dict, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    badge = badge_svg(verdict["status"], verdict["config"])
    (out_dir / "badge.svg").write_text(badge, encoding="utf-8")
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    page = _env().get_template("run.html.j2").render(
        v=verdict, badge=badge, colour=COLOURS[verdict["status"]], explanation=explanation(verdict),
        scope=scope_statement(verdict["config"]), layer_names=LAYER_NAMES,
        layers=[L for L in ("A", "B", "C") if L in verdict["findings"]])
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    return {"badge": str(out_dir / "badge.svg"), "page": str(out_dir / "index.html"),
            "verdict": str(out_dir / "verdict.json")}


def write_index(reports_dir: Path) -> Path:
    reports_dir = Path(reports_dir)
    rows = []
    for p in (reports_dir / "runs").glob("*/verdict.json"):
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows.append({"v": v, "badge": badge_svg(v["status"], v["config"]), "href": f"runs/{p.parent.name}/index.html"})
    rows.sort(key=lambda r: ((r["v"].get("window") or {}).get("end", ""), r["v"].get("verified_at", "")), reverse=True)
    out = reports_dir / "index.html"
    out.write_text(_env().get_template("index.html.j2").render(rows=rows), encoding="utf-8")
    return out
