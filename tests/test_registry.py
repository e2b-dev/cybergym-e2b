import pytest

from cybergym_e2b.registry import task_images


def test_arvo_image_contract() -> None:
    images = task_images("arvo:1065")
    assert images.vulnerable == "n132/arvo:1065-vul"
    assert images.fixed == "n132/arvo:1065-fix"


def test_oss_fuzz_image_contract() -> None:
    images = task_images("oss-fuzz:42535201")
    assert images.vulnerable == "cybergym/oss-fuzz:42535201-vul"


def test_unknown_family_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        task_images("future:1")
