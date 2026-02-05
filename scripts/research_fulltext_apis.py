"""
Research Fulltext APIs - Find all available sources for PDF/fulltext retrieval
"""

import asyncio
import httpx
import json


async def research_apis():
    """Research available fulltext APIs"""

    print("=" * 70)
    print("Fulltext API Research - Finding Missing Sources")
    print("=" * 70)

    apis = [
        # Internet Archive Scholar
        (
            "Internet Archive Scholar",
            "https://scholar.archive.org/search?q=covid&limit=1",
            "Check for fulltext links",
        ),
        # CrossRef Works with links
        (
            "CrossRef Links",
            "https://api.crossref.org/works/10.1038/nature12373?mailto=test@example.com",
            "Check link field",
        ),
        # OpenAIRE Research Graph API
        (
            "OpenAIRE",
            "https://api.openaire.eu/search/publications?doi=10.1038/nature12373&format=json",
            "European OA publications",
        ),
        # DOAJ API
        (
            "DOAJ",
            "https://doaj.org/api/search/articles/doi:10.1371/journal.pone.0185809",
            "OA journal directory",
        ),
        # Zenodo
        (
            "Zenodo",
            "https://zenodo.org/api/records?q=covid&size=1",
            "Research data repository",
        ),
        # PubMed Linkout (via elink)
        (
            "PubMed Linkout",
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&id=23903782&cmd=llinks&retmode=json",
            "External links from PubMed",
        ),
        # Dissemin
        (
            "Dissemin",
            "https://dissem.in/api/10.1038/nature12373",
            "OA availability checker",
        ),
        # SHARE
        (
            "SHARE",
            "https://share.osf.io/api/v2/search/creativeworks?q=covid",
            "Open research data",
        ),
    ]

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for name, url, description in apis:
            try:
                resp = await client.get(
                    url, headers={"User-Agent": "pubmed-search-mcp/1.0"}
                )
                status = resp.status_code

                print(f"\n{name}:")
                print(f"  Description: {description}")
                print(f"  Status: {status}")

                if status == 200:
                    try:
                        data = resp.json()
                        # Show relevant fields based on API
                        if "results" in data:
                            print(f"  Results: {len(data.get('results', []))}")
                        if "message" in data:
                            msg = data["message"]
                            if "link" in msg:
                                links = msg.get("link", [])
                                print(f"  Links: {len(links)}")
                                # Show first PDF link
                                for link in links[:3]:
                                    content_type = link.get(
                                        "content-type", ""
                                    )
                                    if "pdf" in content_type.lower():
                                        print(f"    PDF: {link.get('URL', '')[:60]}")
                        if "response" in data:
                            docs = data.get("response", {}).get("docs", [])
                            print(f"  Docs: {len(docs)}")
                        if "linksets" in data:
                            linksets = data.get("linksets", [])
                            print(f"  Linksets: {len(linksets)}")
                            for ls in linksets[:1]:
                                idurllist = ls.get("idurllist", [])
                                print(f"  URLs in linkset: {len(idurllist)}")
                        if "hits" in data:
                            hits = data.get("hits", {})
                            print(f"  Total: {hits.get('total', 0)}")
                        if "records" in data:
                            print(f"  Records: {len(data.get('records', []))}")
                        if "paper" in data:
                            paper = data.get("paper", {})
                            print(f"  OA: {paper.get('pdf_url', 'N/A')[:50]}")
                    except json.JSONDecodeError:
                        ct = resp.headers.get("content-type", "")
                        print(f"  Content-Type: {ct}")
                        if "xml" in ct:
                            print(f"  (XML response - parseable)")
                elif status == 404:
                    print("  Not found (but API works)")
                else:
                    print(f"  Response: {resp.text[:80]}")

            except Exception as e:
                print(f"\n{name}:")
                print(f"  Error: {str(e)[:70]}")


if __name__ == "__main__":
    asyncio.run(research_apis())
