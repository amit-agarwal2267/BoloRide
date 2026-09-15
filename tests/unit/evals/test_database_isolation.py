import pytest

from boloride.evals.database_isolation import disposable_database_urls


def test_disposable_database_url_uses_explicit_target() -> None:
    admin, target = disposable_database_urls(
        "postgresql+asyncpg://user:secret@postgres/boloride",
        "boloride_eval_c3_a1",
    )
    assert admin.endswith("/postgres")
    assert target.endswith("/boloride_eval_c3_a1")

    _, candidate_five = disposable_database_urls(
        "postgresql+asyncpg://user:secret@postgres/boloride",
        "boloride_eval_c5_a3",
    )
    assert candidate_five.endswith("/boloride_eval_c5_a3")

    _, candidate_six = disposable_database_urls(
        "postgresql+asyncpg://user:secret@postgres/boloride",
        "boloride_eval_c6_a1",
    )
    assert candidate_six.endswith("/boloride_eval_c6_a1")


@pytest.mark.parametrize(
    "unsafe_name",
    ("boloride", "postgres", "boloride_eval", "boloride_eval_c3_a4", "other_eval_c3_a1"),
)
def test_disposable_database_guard_rejects_unsafe_names(unsafe_name: str) -> None:
    with pytest.raises(ValueError, match="refusing non-disposable"):
        disposable_database_urls(
            "postgresql+asyncpg://user:secret@postgres/boloride",
            unsafe_name,
        )
