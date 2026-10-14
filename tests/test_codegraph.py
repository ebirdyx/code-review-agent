"""The lightweight code graph: callers, callees, tests and class context around changed functions.

Pure functions on small in-memory repositories, so the exact behaviour is pinned down. Several cases are bugs that
showed up when the module was first tried on the real demo repository.
"""

from code_review_agent.codegraph import MAX_TOTAL_CHARS, build_pack, is_test_path

SERVICE = '''\
class Service:
    def __init__(self, store):
        self.store = store

    def escalate(self, now):
        """Raise the priority of old tickets."""
        items = self.store.list_open()
        for item in items:
            if now - item.created > 48:
                self.store.save(item)
        return items

    def other(self):
        return 1
'''

STORE = '''\
class Store:
    def list_open(self):
        return []

    def save(self, item):
        return item
'''

JOB = '''\
from service import Service


def nightly(service):
    return service.escalate(0)
'''

TEST = '''\
from service import Service


def test_escalate_old():
    assert Service(None).escalate(100) == []


def test_unrelated():
    assert 1 == 1
'''

REPO = {"service.py": SERVICE, "store.py": STORE, "job.py": JOB, "tests/test_service.py": TEST}
ESCALATE_LINES = {"service.py": {9}}  # one added line inside `escalate`


def kinds(snippets):
    return sorted((s.kind, s.name) for s in snippets)


def test_finds_callers_callees_tests_and_the_class_constructor():
    snippets, facts = build_pack(ESCALATE_LINES, REPO)
    assert kinds(snippets) == [
        ("callee", "Store.list_open"), ("callee", "Store.save"),
        ("caller", "nightly"), ("class", "Service.__init__"), ("test", "test_escalate_old"),
    ]
    assert all(s.symbol == "Service.escalate" for s in snippets)
    assert facts == ["`Service.escalate` (service.py) is called by 1 other repository function(s) and mentioned in 1 test function(s)."]


def test_snippets_carry_real_line_numbers_and_the_exact_source():
    snippets, _ = build_pack(ESCALATE_LINES, REPO)
    caller = next(s for s in snippets if s.kind == "caller")
    assert (caller.path, caller.start_line, caller.end_line) == ("job.py", 4, 5)
    assert caller.text == "def nightly(service):\n    return service.escalate(0)"
    save = next(s for s in snippets if s.name == "Store.save")
    assert REPO["store.py"].splitlines()[save.start_line - 1] == "    def save(self, item):"


def test_a_function_nobody_calls_and_no_test_mentions_is_said_plainly():
    snippets, facts = build_pack({"service.py": {14}}, REPO)  # inside `other`
    assert [s for s in snippets if s.kind in ("caller", "test")] == []
    assert facts == ["`Service.other` (service.py) is called by 0 other repository function(s) and mentioned in no test function."]


def test_tests_added_by_the_change_count_but_are_not_repeated_as_snippets():
    """Bug seen on the real repo: the PR's own tests were reported as 'no test mentions it'."""
    added = {"service.py": {9}, "tests/test_service.py": {4, 5}}  # the PR also adds test_escalate_old
    snippets, facts = build_pack(added, REPO)
    assert not [s for s in snippets if s.kind == "test"]  # already in the diff, so not shown twice
    assert "mentioned in 1 test function(s) (1 added or changed by this change)" in facts[0]


def test_a_test_function_is_not_itself_the_subject_of_the_search():
    """Bug seen on the real repo: the callees of the PR's new tests cluttered the pack."""
    snippets, facts = build_pack({"tests/test_service.py": {4, 5}}, REPO)
    assert snippets == [] and facts == []


def test_constructors_are_found_by_the_name_of_their_class():
    app = "from service import Service\n\n\ndef main():\n    return Service(1)\n"
    repo = {**REPO, "app.py": app}
    snippets, facts = build_pack({"service.py": {3}}, repo)  # inside __init__
    assert any(s.kind == "caller" and s.name == "main" for s in snippets)
    assert any("`Service.__init__`" in f and "called by 1 other" in f and "mentioned in 1 test function(s)" in f for f in facts)


def test_a_caller_that_is_also_in_the_diff_is_counted_but_not_repeated():
    added = {"service.py": {9}, "job.py": {5}}
    snippets, facts = build_pack(added, REPO)
    assert not [s for s in snippets if s.kind == "caller"]
    assert "called by 1 other repository function(s)" in next(f for f in facts if "Service.escalate" in f)


def test_generic_names_are_not_followed():
    """`get` defined in many classes would point at the wrong function, so it is skipped."""
    many = {f"m{i}.py": f"class C{i}:\n    def get(self):\n        return {i}\n" for i in range(5)}
    user = {"u.py": "def use(x):\n    return x.get()\n"}
    snippets, _ = build_pack({"u.py": {2}}, {**many, **user})
    assert [s for s in snippets if s.kind == "callee"] == []


def test_a_file_that_does_not_parse_is_skipped_not_fatal():
    snippets, _ = build_pack(ESCALATE_LINES, {**REPO, "broken.py": "def (:\n"})
    assert any(s.kind == "caller" for s in snippets)


def test_only_python_files_that_exist_are_searched_for_changed_functions():
    assert build_pack({"missing.py": {1}}, REPO) == ([], [])
    assert build_pack({}, REPO) == ([], [])


def test_long_functions_are_cut_with_a_visible_marker_and_a_correct_end_line():
    body = "".join(f"    x{i} = {i}\n" for i in range(100))
    repo = {"big.py": "def big():\n" + body, "use.py": "def go():\n    big()\n    return 1\n"}
    snippets, _ = build_pack({"use.py": {2}}, repo)
    big = next(s for s in snippets if s.name == "big")
    assert big.end_line == big.start_line + 59 and "more lines not shown" in big.text


def test_the_total_size_is_capped_and_the_cut_is_reported():
    nl = "\n"
    helpers = {f"h{i}.py": f"def helper{i}():{nl}" + "".join(f"    y{j} = {j}{nl}" for j in range(59)) for i in range(30)}
    # eight changed functions, three big callees each: more than the budget allows
    go = "".join(f"def f{k}():{nl}" + "".join(f"    helper{3 * k + n}(){nl}" for n in range(3)) for k in range(8))
    added = {"go.py": set(range(1, go.count(nl) + 2))}
    snippets, facts = build_pack(added, {**helpers, "go.py": go})
    assert sum(len(s.text) for s in snippets) <= MAX_TOTAL_CHARS
    assert any("cut at" in f for f in facts)


def test_nested_functions_report_the_inner_one_not_the_container():
    src = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
    _, facts = build_pack({"n.py": {3}}, {"n.py": src})
    assert any("`outer.inner`" in f for f in facts) and not any("`outer` " in f for f in facts)


def test_test_path_detection():
    assert is_test_path("tests/test_a.py") and is_test_path("pkg/test/x.py") and is_test_path("a/b_test.py")
    assert is_test_path("conftest.py") and not is_test_path("src/testing_tools.py") and not is_test_path("pkg/service.py")
