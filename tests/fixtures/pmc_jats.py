"""Synthetic NCBI ``efetch db=pmc`` payloads shaped like real PMC JATS records.

The structure mirrors what E-utilities returns (XML declaration, articleset
DOCTYPE, namespaced attributes, processing instructions, nested sections,
tables, permissions and references). All prose and numbers are synthetic and
are not research evidence.
"""

from __future__ import annotations

PMC_ARTICLESET_PROLOG = (
    '<?xml version="1.0"  ?>'
    '<!DOCTYPE pmc-articleset PUBLIC "-//NLM//DTD ARTICLE SET 2.0//EN" '
    '"https://dtd.nlm.nih.gov/ncbi/pmc/articleset/nlm-articleset-2.0.dtd">'
)

_FRONT = """<front>
<journal-meta><journal-id journal-id-type="nlm-ta">Synthetic Med J</journal-id>
<journal-title-group><journal-title>Synthetic Medical Journal</journal-title></journal-title-group>
<issn pub-type="ppub">0000-0000</issn><publisher><publisher-name>Synthetic Press</publisher-name></publisher></journal-meta>
<article-meta>
<article-id pub-id-type="pmid">12345678</article-id>
<article-id pub-id-type="pmc">7096777</article-id>
<article-id pub-id-type="doi">10.1000/smoke</article-id>
<title-group><article-title>Synthetic EEG-guided anesthesia trial &#x2013; a fixture</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Smith</surname><given-names>J</given-names></name></contrib></contrib-group>
<pub-date pub-type="ppub"><year>2024</year></pub-date>
{permissions}
<abstract><sec><title>Importance</title><p>Synthetic abstract importance.</p></sec>
<sec><title>Results</title><p>Abstract-only result sentence that must never stand in for the body.</p></sec></abstract>
</article-meta>
</front>"""

_PERMISSIONS = """<permissions><copyright-statement>Synthetic copyright</copyright-statement>
<license license-type="open-access" xlink:href="https://creativecommons.org/licenses/by/4.0/">
<license-p>Synthetic CC-BY license statement.</license-p></license></permissions>"""

_BODY = """<body>
<sec id="s1"><title>Introduction</title><p>Synthetic introduction with <italic>inline</italic> markup.</p></sec>
<sec id="s2"><title>Methods</title>
<sec id="s2a"><title>Trial Design</title><p>Synthetic randomized design paragraph.</p></sec>
<sec id="s2b"><title>Outcomes</title><p>Synthetic primary outcome definition.</p></sec></sec>
<sec id="s3"><title>Results</title>
<p>Synthetic delirium occurred in 11/100 patients versus 9/101 patients (fixture numbers).</p>
<table-wrap id="t1"><label>Table 1</label><caption><p>Synthetic table</p></caption>
<table><tr><td>Arm</td><td>Events</td></tr></table></table-wrap></sec>
<sec id="s4"><title>Discussion</title><p>Synthetic discussion paragraph.</p></sec>
</body>"""

_BACK = """<back><ref-list><ref id="r1"><label>1</label>
<element-citation publication-type="journal"><article-title>Synthetic reference</article-title>
<pub-id pub-id-type="pmid">11111111</pub-id></element-citation></ref></ref-list></back>"""


def _article(*, body: str, permissions: str = _PERMISSIONS, pi: str = "") -> str:
    return (
        PMC_ARTICLESET_PROLOG
        + "<pmc-articleset>"
        + '<article xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML" '
        + 'xmlns:ali="http://www.niso.org/schemas/ali/1.0/" article-type="research-article" dtd-version="1.3">'
        + pi
        + _FRONT.format(permissions=permissions)
        + body
        + _BACK
        + "</article></pmc-articleset>"
    )


PMC_EFETCH_FULL_BODY = _article(body=_BODY, pi="<?properties open_access?>")

# NCBI keeps only front matter when the publisher forbids XML redistribution.
PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT = _article(
    body="<!--The publisher of this article does not allow downloading of the full text in XML form.-->",
    permissions="<permissions><copyright-statement>Synthetic publisher copyright</copyright-statement></permissions>",
    pi="<?properties manuscript?>",
)

# Same restriction rendered as body text; it must not become a "Body" section.
PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH = _article(
    body=("<body><p>The publisher of this article does not allow downloading of the full text in XML form.</p></body>"),
    permissions="<permissions><copyright-statement>Synthetic publisher copyright</copyright-statement></permissions>",
)

PMC_EFETCH_NO_ARTICLE = (
    '<?xml version="1.0"  ?><pmc-articleset><error id="99999999">'
    "The following PMCID is not available: 99999999</error></pmc-articleset>"
)

# HTTP 200 answers that state nothing about the article: an E-utilities error
# envelope, an empty body, or an articleset without any per-ID statement.
PMC_EFETCH_EUTILS_ERROR = '<?xml version="1.0" ?><eFetchResult><ERROR>Unable to obtain query #1</ERROR></eFetchResult>'
PMC_EFETCH_EMPTY_BODY = ""
PMC_EFETCH_EMPTY_ARTICLESET = PMC_ARTICLESET_PROLOG + "<pmc-articleset></pmc-articleset>"

PUBMED_ESUMMARY_WITH_PMC = {
    "header": {"type": "esummary", "version": "0.3"},
    "result": {
        "uids": ["12345678"],
        "12345678": {
            "uid": "12345678",
            "title": "Synthetic EEG-guided anesthesia trial",
            "articleids": [
                {"idtype": "pubmed", "idtypen": 1, "value": "12345678"},
                {"idtype": "doi", "idtypen": 3, "value": "10.1000/smoke"},
                {"idtype": "pmc", "idtypen": 8, "value": "PMC7096777"},
                {"idtype": "pmcid", "idtypen": 5, "value": "pmc-id: PMC7096777;"},
            ],
        },
    },
}

__all__ = [
    "PMC_EFETCH_EMPTY_ARTICLESET",
    "PMC_EFETCH_EMPTY_BODY",
    "PMC_EFETCH_EUTILS_ERROR",
    "PMC_EFETCH_FRONT_MATTER_ONLY_COMMENT",
    "PMC_EFETCH_FRONT_MATTER_ONLY_PARAGRAPH",
    "PMC_EFETCH_FULL_BODY",
    "PMC_EFETCH_NO_ARTICLE",
    "PUBMED_ESUMMARY_WITH_PMC",
]
