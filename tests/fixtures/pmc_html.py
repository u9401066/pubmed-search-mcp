"""Synthetic PMC article pages shaped like ``https://pmc.ncbi.nlm.nih.gov/articles/PMC.../``.

The markup mirrors the current PMC article viewer: a government banner, site
header and navigation, a journal banner, the article citation block with a
hidden journal menu, front matter with author pop-ups and collapsible
"Copyright and License information" panel, Key Points and Abstract blocks,
nested body sections with table wraps and figures, supplementary boxes, a
reference list, an "Associated Data" block, the courtesy footer, the
side navigation (ACTIONS / RESOURCES / Cite dialog) and the site footer.

All prose, numbers, names and links are synthetic fixture content and are not
research evidence.
"""

from __future__ import annotations

FIXTURE_PMCID = "PMC7000001"
FIXTURE_PMID = "39000001"
FIXTURE_DOI = "10.5555/fixture.2024.001"

_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="ncbi_app" content="cloudpmc-viewer" />
<meta name="ncbi_db" content="pmc" />
<meta name="citation_journal_title" content="Synthetic Journal of Fixtures">
<meta name="citation_title" content="Guided anesthesia fixture trial">
<meta name="citation_author" content="Ada Fixture">
<meta name="citation_doi" content="{doi}">
<meta name="citation_pmid" content="{pmid}">
{pdf_meta}
<meta name="citation_fulltext_html_url" content="https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/">
<link rel="canonical" href="https://pmc.ncbi.nlm.nih.gov/articles/{canonical}/">
<title>Guided anesthesia fixture trial - PMC</title>
<script>window.ncbi = {{"tracking": "Search in PMC script text"}};</script>
<style>.pmc-wm {{ background: none; }}</style>
</head>
<body>
<section class="usa-banner" aria-label="Official website of the United States government">
<header class="usa-banner__header"><p>An official website of the United States government</p></header>
</section>
<header class="usa-header usa-header--extended" data-header>
<nav aria-label="Primary navigation" class="usa-nav"><ul><li><a href="/">PMC Home</a></li><li>Search in PMC navigation</li></ul></nav>
</header>
<section class="pmc-header pmc-header--basic" aria-label="PMC Header with search box">
<form><input name="term" value="search box text"><button>Search</button></form>
</section>
<div class="usa-modal" id="permalink"><h2 class="usa-modal__heading">PERMALINK</h2><button>Copy</button></div>
<main id="main-content" class="usa-layout-docs">
<section class="pmc-journal-banner" aria-label="Journal banner"><img src="https://cdn.example.test/logo.png" alt="Journal logo"></section>
"""

_ARTICLE = """<article lang="en"><section aria-label="Article citation and metadata">
<section class="pmc-layout__citation font-secondary font-xs"><div>
<div class="display-inline-block"><button type="button" aria-controls="journal_context_menu">Synth J Fixt</button></div>. 2024 Jan 2;1(1):1-9. doi: <a href="https://doi.org/{doi}" class="usa-link">{doi}</a>
</div>
<nav id="journal_context_menu" hidden="hidden"><ul class="menu-list"><li><a href="/search/">Search in PMC</a></li></ul></nav>
</section>
<section class="front-matter"><div class="ameta p font-secondary font-xs">
<hgroup><h1>Guided anesthesia fixture trial</h1>
<p>A Synthetic Randomized Fixture</p></hgroup>
<div class="cg p">
<a href="https://pubmed.ncbi.nlm.nih.gov/?term=Fixture" class="usa-link" aria-describedby="id1"><span class="name western">Ada Fixture</span></a>
<div hidden="hidden" id="id1"><h3><span class="name western">Ada Fixture</span></h3>
<div class="p">Find articles by <a href="#">Ada Fixture</a></div></div>
<sup>1</sup>
</div>
<ul class="d-buttons inline-list">
<li><button class="d-button" aria-controls="aip_a">Author information</button></li>
<li><button class="d-button" aria-controls="clp_a">Copyright and License information</button></li>
</ul>
<div class="d-panels font-secondary-light">
<div id="aip_a" class="d-panel p" style="display: none"><div class="p" id="aff1"><sup>1</sup>Department of Fixtures, Example University</div>
<div class="author-notes p"><div class="fn"><p><strong>Corresponding Author:</strong> Ada Fixture (fixture@example.test).</p></div></div></div>
<div id="clp_a" class="d-panel p" style="display: none">
<div>{license_statement}</div>
{license_paragraph}
<div class="p"><a href="/about/copyright/" class="usa-link">PMC Copyright notice</a></div>
</div>
</div>
<div>PMCID: {pmcid}  PMID: <a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" class="usa-link">{pmid}</a></div>
<div class="ra xbox p" role="complementary" aria-label="Related or updated information about this article">
<div>See editorial "<a href="/articles/PMC7000002/" class="usa-link">A related fixture editorial</a>".</div>
</div>
</div></section></section>
<section aria-label="Article content"><section class="body main-article-body">
{body}
</section>
<footer class="p courtesy-note font-secondary font-sm text-center"><hr class="headless">
<p>Articles from Synthetic Journal of Fixtures are provided here courtesy of <strong>Fixture Press</strong></p></footer>
</section></article>
"""

_BODY = """<section class="abstract" id="abstract1"><h2>Key Points</h2>
<section id="ab-1"><h3 class="pmc_sec_title">Question</h3><p>Key-point question that must not replace the abstract.</p></section>
<section id="ab-2"><h3 class="pmc_sec_title">Findings</h3><p>Key-point finding sentence.</p></section>
</section>
<section class="abstract" id="abstract2"><h2>Abstract</h2>
<section id="ab-3"><h3 class="pmc_sec_title">Importance</h3><p>Synthetic abstract importance.</p></section>
<section id="ab-4"><h3 class="pmc_sec_title">Results</h3><p>Abstract-only result: 11 of 100 versus 9 of 101 (fixture).</p></section>
</section>
<section class="kwd-group"><p><strong>Keywords:</strong> fixture, anesthesia</p></section>
<section id="H1-1"><h2 class="pmc_sec_title">Introduction</h2>
<p>Synthetic introduction with <em>inline</em> markup and a citation.<sup><a href="#r1" class="usa-link" aria-describedby="r1">1</a></sup></p>
</section>
<section id="H1-2"><h2 class="pmc_sec_title">Methods</h2>
<section id="H2-1"><h3 class="pmc_sec_title">Trial Design</h3><p>Synthetic randomized design paragraph.</p>
<ul><li>Inclusion item one.</li><li>Inclusion item two.</li></ul></section>
<section id="H2-2"><h3 class="pmc_sec_title">Outcomes</h3><p>Synthetic primary outcome definition.</p></section>
</section>
<section id="H1-3"><h2 class="pmc_sec_title">Results</h2>
<p>Synthetic results overview paragraph.</p>
<section class="tw xbox font-sm" id="t1"><h3 class="obj_head">Table 1.  Fixture Baseline Characteristics.</h3>
<div class="tbl-box p" tabindex="0"><table class="content"><thead><tr><th>Arm</th><th>No.</th></tr></thead>
<tbody><tr><td>Table-only cell Arm A</td><td>100</td></tr></tbody></table></div>
<div class="tw-foot p"><div class="fn"><p class="display-inline">Table footnote text.</p></div></div></section>
<figure class="fig xbox font-sm" id="f1"><h3 class="obj_head">Figure 1.  Fixture Flow Diagram.</h3>
<p class="img-box line-height-none text-center"><a class="tileshop" href="https://www.ncbi.nlm.nih.gov/core/lw/2.0/html/tileshop_pmc/tileshop_pmc_inline.html"><img class="graphic zoom-in" src="https://cdn.ncbi.nlm.nih.gov/pmc/blobs/fixture/f1.jpg" alt="Figure 1."></a></p>
<div class="p text-right font-secondary"><a href="figure/f1/" class="usa-link">Open in a new tab</a></div>
<figcaption><p>Figure caption text describing the synthetic flow.</p></figcaption></figure>
<section id="H2-3"><h3 class="pmc_sec_title">Primary Outcome</h3>
<p>Synthetic delirium occurred in 11 of 100 patients (11.0%) in the guided group and 9 of 101 patients (8.9%) in the usual care group (fixture numbers).</p></section>
</section>
<section id="H1-4"><h2 class="pmc_sec_title">Discussion</h2><p>Synthetic discussion paragraph.</p></section>
<section id="H1-5"><h2 class="pmc_sec_title">Conclusions</h2><p>Synthetic conclusion paragraph.</p></section>
<section id="note-1"><section class="sm xbox font-sm" id="note-1-s"><div class="caption p"><span>Supplement 1.</span><p>Supplementary fixture protocol</p></div>
<div class="media p"><div class="caption"><a href="/articles/instance/7000001/bin/s001.pdf" class="usa-link">Click here for additional data file.</a></div></div></section></section>
<section id="ref-list1" class="ref-list"><h2 class="pmc_sec_title">References</h2>
<section><ul class="ref-list font-sm" style="list-style-type:none">
<li id="r1"><span class="label">1.</span><cite>Fixture A, Example B. A synthetic reference. Fixture J. 2020;1:1-2. doi: 10.5555/ref.one</cite> [<a href="https://doi.org/10.5555/ref.one" class="usa-link usa-link--external">DOI</a>] [<a href="https://pubmed.ncbi.nlm.nih.gov/31000001/" class="usa-link">PubMed</a>] [<a href="https://scholar.google.com/scholar_lookup?x" class="usa-link">Google Scholar</a>]</li>
<li id="r2"><span class="label">2.</span><cite>Second synthetic reference without identifiers.</cite> [<a href="https://scholar.google.com/scholar_lookup?y" class="usa-link">Google Scholar</a>]</li>
</ul></section></section>
<section id="_ad1_" class="associated-data"><h2 class="pmc_sec_title">Associated Data</h2>
<p class="font-secondary"><em>This section collects any data citations, data availability statements, or supplementary materials included in this article.</em></p></section>"""

_SIDE_AND_FOOTER = """</main>
<section class="pmc-sidenav__container" aria-label="Article resources and navigation">
<section><h2 class="margin-top-0">ACTIONS</h2><ul><li><a href="#">View on publisher site</a></li><li><button>Cite</button></li></ul></section>
<section class="pmc-resources"><h2>RESOURCES</h2><h3 class="usa-accordion__heading">Similar articles</h3></section>
</section>
<div class="usa-modal" id="cite-dialog"><h2 class="usa-modal__heading">Cite</h2><p>Cite dialog text</p></div>
<footer class="ncbi-footer ncbi-dark-background"><p>Connect with NLM footer text</p></footer>
</body>
</html>
"""

_NO_BODY = """<section class="abstract" id="abstract1"><h2>Abstract</h2>
<p>Only an abstract is shown for this scanned fixture article.</p></section>
<section id="ref-list1" class="ref-list"><h2 class="pmc_sec_title">References</h2></section>"""


def pmc_article_page(
    *,
    pmcid: str = FIXTURE_PMCID,
    canonical: str | None = None,
    body: str = _BODY,
    pdf_url: str | None = None,
    open_access: bool = False,
) -> str:
    """Return a full PMC-shaped article page."""
    if open_access:
        statement = "This article is copyright of the authors, 2024."
        paragraph = (
            "<p>This is an open-access article distributed under the terms of the "
            '<a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution (CC BY 4.0)</a> '
            "Licence.</p>"
        )
    else:
        statement = "Copyright 2024 Fixture Press. All Rights Reserved."
        paragraph = ""
    pdf_meta = f'<meta name="citation_pdf_url" content="{pdf_url}">' if pdf_url else ""
    return (
        _HEAD.format(
            doi=FIXTURE_DOI,
            pmid=FIXTURE_PMID,
            pmcid=pmcid,
            canonical=canonical or pmcid,
            pdf_meta=pdf_meta,
        )
        + _ARTICLE.format(
            doi=FIXTURE_DOI,
            pmid=FIXTURE_PMID,
            pmcid=pmcid,
            body=body,
            license_statement=statement,
            license_paragraph=paragraph,
        )
        + _SIDE_AND_FOOTER
    )


PMC_ARTICLE_PAGE = pmc_article_page()
ABSTRACT_ONLY_BODY = _NO_BODY
PMC_ARTICLE_PAGE_WITHOUT_BODY = pmc_article_page(body=_NO_BODY)
# Shape of the CAPTCHA interstitial NCBI's web front end serves (HTTP 200) to
# automated traffic it distrusts; trimmed and with synthetic tokens.
PMC_CHALLENGE_PAGE = """<!doctype html><html lang="en" dir="ltr"><head>
<base href="https://www.google.com/recaptcha/challengepage/"><meta name="referrer" content="origin">
<script nonce="fixture">window['ppConfig'] = {productName: 'RecaptchaChallengePageUi'};</script>
</head><body><div class="g-recaptcha" data-sitekey="fixture-key"></div>
<noscript>Please enable JavaScript to continue.</noscript></body></html>"""
PMC_ERROR_PAGE = """<!DOCTYPE html><html><head><title>PMC maintenance</title></head>
<body><main><h1>Service temporarily unavailable</h1><p>Please try again later.</p></main></body></html>"""

GENERIC_ARTICLE_HTML = """<!DOCTYPE html><html><head>
<meta name="citation_title" content="Generic publisher fixture">
</head><body>
<header class="site-header"><nav><a href="/">Journal home navigation</a></nav></header>
<div class="cookie-banner"><p>We use cookies text</p></div>
<article>
<h1>Generic publisher fixture</h1>
<h2>Abstract</h2><p>Generic abstract sentence.</p>
<h2>Methods</h2><p>Generic methods paragraph.</p>
<aside class="related"><p>Related articles sidebar</p></aside>
<h2>Results</h2><p>Generic results paragraph with 3 of 30 events.</p>
<div class="share-tools"><p>Share on social media</p></div>
</article>
<footer><p>Publisher footer text</p></footer>
</body></html>"""
