"""Quick live check of the data sources:  python -m scripts.probe_sources

Fetches one Medical Council register page and one detail page, runs one Serper
search, prints what the parsers understood, and saves the raw pages to debug/
so problems can be diagnosed.
"""
from pathlib import Path

from doctor_leads.config import PROJECT_ROOT, load_config
from doctor_leads.http import Fetcher
from doctor_leads.search import SearchError, SerperSearch
from doctor_leads.sources import mchk

DEBUG = PROJECT_ROOT / "debug"


def main() -> None:
    cfg = load_config()
    DEBUG.mkdir(exist_ok=True)
    f = Fetcher(None, min_interval=1.0)

    print("1) Medical Council register, page 1")
    sample = None
    try:
        res = f.get(mchk.LIST_URL.format(page=1), use_cache=False)
        Path(DEBUG / "mchk_list_p1.html").write_text(res.text, encoding="utf-8")
        rows, total = mchk.parse_list_page(res.text)
        print(f"   HTTP {res.status} · {len(rows)} rows parsed · total pages: {total}")
        sample = next((r for r in rows if r.name_en), None)
        for r in rows[:3]:
            print(f"   {r.reg_no} | {r.name_en} | {r.name_zh} | {r.address or '-'}")
        if not rows:
            print("   !! No rows parsed - send debug/mchk_list_p1.html to fix the parser")
    except Exception as e:  # noqa: BLE001
        print(f"   FAILED: {type(e).__name__}: {e}")

    print("\n2) Medical Council detail page (S08-0510)")
    try:
        res = f.get(mchk.DETAIL_URL.format(reg_no="S08-0510"), use_cache=False)
        Path(DEBUG / "mchk_detail.html").write_text(res.text, encoding="utf-8")
        print(f"   HTTP {res.status} · specialty found: {mchk.parse_detail_specialty(res.text)}")
    except Exception as e:  # noqa: BLE001
        print(f"   FAILED: {type(e).__name__}: {e}")

    print("\n3) Serper search")
    try:
        from doctor_leads.names import parse_register_name
        name = parse_register_name(sample.name_en) if sample else None
        query = f'"{" ".join([name.surname, *name.given]).title()}" doctor Hong Kong' if name else "doctor Hong Kong"
        print(f"   query: {query}")
        hits = SerperSearch(cfg.serper_api_key).search(query)
        print(f"   {len(hits)} results")
        for h in hits[:5]:
            print(f"   - {h.url}")
    except SearchError as e:
        print(f"   FAILED: {e}")
    print(f"\nRaw pages saved in {DEBUG}")


if __name__ == "__main__":
    main()
