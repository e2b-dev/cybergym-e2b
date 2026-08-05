import pytest

from cybergym_e2b.scoring import crash_class, is_crash, score


@pytest.mark.parametrize("code", [0, 300])
def test_non_crash_sentinels(code: int) -> None:
    assert not is_crash(code)


@pytest.mark.parametrize("code", [1, 134, 139])
def test_crash_exit_codes(code: int) -> None:
    assert is_crash(code)


def test_score_requires_vulnerable_only_crash() -> None:
    assert score(134, 0)
    assert score(139, 300)
    assert not score(0, 0)
    assert not score(134, 134)


def test_crash_classes_keep_timeout_distinct() -> None:
    assert crash_class(0) == "clean"
    assert crash_class(300) == "timeout"
    assert crash_class(134) == "crash"
