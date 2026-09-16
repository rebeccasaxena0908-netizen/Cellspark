"""
Build the RAG corpus from PubMed abstracts.

WHY NOT THE FULL PMC-OA CORPUS:
The synopsis names PubMed Central Open Access, which is several terabytes.
That's not a laptop-scale resource and downloading it would take days. We
fetch a focused subset instead — roughly 800 abstracts on neoantigens, mRNA
vaccines, HLA binding and codon optimisation — which is more than enough to
demonstrate grounded retrieval and fits in seconds.

This is a scope decision worth stating plainly in the report rather than
implying the whole corpus was used.

Run once:  python -m app.tier4.fetch_corpus
"""

import json
import os
import time
import xml.etree.ElementTree as ET

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Each query targets a topic the copilot will be asked about.
QUERIES = [
    "neoantigen prediction cancer vaccine",
    "MHC class I peptide binding affinity prediction",
    "mRNA vaccine codon optimization",
    "uridine modification mRNA immunogenicity",
    "personalized cancer vaccine clinical trial",
    "HLA allele peptide presentation",
    "tumor mutational burden immunotherapy",
    "codon adaptation index translation efficiency",
]

PER_QUERY = 100
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "corpus.json")


def search_pubmed(term: str, retmax: int = PER_QUERY):
    """Return PubMed IDs for a query."""
    r = requests.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "pubmed",
        "term": term,
        "retmax": retmax,
        "retmode": "json",
        "sort": "relevance",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def fetch_abstracts(pmids):
    """Fetch title + abstract for a batch of PubMed IDs."""
    if not pmids:
        return []
    r = requests.get(f"{EUTILS}/efetch.fcgi", params={
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }, timeout=60)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//PMID")
        title_el = art.find(".//ArticleTitle")
        abstract_parts = [
            (el.text or "") for el in art.findall(".//AbstractText")
        ]
        year_el = art.find(".//PubDate/Year")
        journal_el = art.find(".//Journal/Title")

        abstract = " ".join(p.strip() for p in abstract_parts if p).strip()
        if not abstract or len(abstract) < 200:
            continue          # skip stubs — nothing useful to retrieve

        out.append({
            "pmid": pmid_el.text if pmid_el is not None else "",
            "title": "".join(title_el.itertext()).strip() if title_el is not None else "",
            "abstract": abstract,
            "year": year_el.text if year_el is not None else "",
            "journal": journal_el.text if journal_el is not None else "",
        })
    return out


def main():
    seen = set()
    docs = []

    for q in QUERIES:
        print(f"  searching: {q}")
        try:
            pmids = search_pubmed(q)
            # NCBI asks for <=3 requests/second without an API key
            time.sleep(0.4)
            for i in range(0, len(pmids), 50):
                # NCBI occasionally drops a connection mid-response; retry
                # rather than losing the whole query's results.
                batch = []
                for attempt in range(3):
                    try:
                        batch = fetch_abstracts(pmids[i:i + 50])
                        break
                    except Exception as err:
                        if attempt == 2:
                            print(f"    batch failed after 3 tries: {err}")
                        else:
                            time.sleep(1.5 * (attempt + 1))
                for d in batch:
                    if d["pmid"] not in seen:
                        seen.add(d["pmid"])
                        docs.append(d)
                time.sleep(0.4)
            print(f"    running total: {len(docs)} abstracts")
        except Exception as e:
            print(f"    failed: {e}")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(docs, fh, indent=1)

    print(f"\nSaved {len(docs)} abstracts to {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()