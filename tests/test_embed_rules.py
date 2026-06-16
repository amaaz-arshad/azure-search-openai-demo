import pytest

from embed_rules import match_url, normalize_rule, normalize_rules, rules_to_frame_ancestors


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("https://Publishone.snap.de/Preise.html", "publishone.snap.de/Preise.html"),  # host lowered, path kept
        ("  *.snap.de  ", "*.snap.de"),
        ("help.customer-website.com/*", "help.customer-website.com/*"),
        ("HTTP://WWW.Example.COM", "www.example.com"),
        ("", None),
        ("   ", None),
        ("/just-a-path", None),  # no host
    ],
)
def test_normalize_rule(rule, expected):
    assert normalize_rule(rule) == expected


def test_normalize_rules_dedupes_and_drops_blanks():
    assert normalize_rules(["*.snap.de", "https://*.snap.de", "", "publishone.snap.de"]) == [
        "*.snap.de",
        "publishone.snap.de",
    ]


def test_empty_whitelist_allows_everything():
    assert match_url([], "https://anything.example.com/page") is True


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://a.snap.de/x", True),
        ("https://deep.sub.snap.de/", True),
        ("https://snap.de/x", False),  # apex excluded by *.snap.de
        ("https://notsnap.de/x", False),
    ],
)
def test_subdomain_wildcard(url, expected):
    assert match_url(["*.snap.de"], url) is expected


def test_exact_host_any_path():
    assert match_url(["publishone.snap.de"], "https://publishone.snap.de/anything?q=1") is True
    assert match_url(["publishone.snap.de"], "https://other.snap.de/anything") is False


def test_exact_path_is_case_sensitive_and_ignores_query():
    rules = ["publishone.snap.de/preise.html"]
    assert match_url(rules, "https://publishone.snap.de/preise.html?ref=x") is True
    assert match_url(rules, "https://publishone.snap.de/preise.HTML") is False
    assert match_url(rules, "https://publishone.snap.de/other.html") is False


def test_path_prefix_wildcard():
    rules = ["help.customer-website.com/*"]
    assert match_url(rules, "https://help.customer-website.com/") is True
    assert match_url(rules, "https://help.customer-website.com/a/b/c") is True
    assert match_url(rules, "https://help.customer-website.com") is True  # bare host = "/"
    assert match_url(rules, "https://help.customer-website.com.evil.com/a") is False


def test_match_url_rejects_unparseable_url():
    assert match_url(["*.snap.de"], "not a url") is False


def test_rules_to_frame_ancestors_drops_paths_and_dedupes():
    value = rules_to_frame_ancestors(["*.snap.de", "publishone.snap.de/preise.html", "publishone.snap.de"])
    assert value == "'self' *.snap.de publishone.snap.de"


def test_rules_to_frame_ancestors_empty_is_allow_all():
    assert rules_to_frame_ancestors([]) == "*"
