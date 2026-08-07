import pytest

from tupacs import envtools
from tupacs.envtools import normalize_remote_url

from .conftest import make_git_repo, requires_git


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:alberto/proj.git", "github.com/alberto/proj"),
        ("https://github.com/alberto/proj.git", "github.com/alberto/proj"),
        ("https://github.com/alberto/proj", "github.com/alberto/proj"),
        ("ssh://git@github.com/alberto/proj.git", "github.com/alberto/proj"),
        ("https://user:token@gitlab.com/group/sub/proj.git", "gitlab.com/group/sub/proj"),
        ("git@BitBucket.org:Team/Repo.git", "bitbucket.org/Team/Repo"),
        ("", None),
    ],
)
def test_normalize_remote_url(url, expected):
    assert normalize_remote_url(url) == expected


@requires_git
def test_slug_from_remote(tmp_path):
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:alberto/proj.git")
    assert envtools.repo_slug(repo) == "github.com/alberto/proj"


@requires_git
def test_slug_local_fallback(tmp_path):
    repo = make_git_repo(tmp_path / "myproj")
    assert envtools.repo_slug(repo) == "local/myproj"


@requires_git
def test_push_pull_roundtrip(vault, tmp_path):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:alberto/proj.git")
    env_file = repo / ".env"
    env_file.write_text("API_KEY=abc123\nDB_URL=postgres://x\n")

    name, action = envtools.push(v, key, env_file, cwd=repo)
    assert name == "env/github.com/alberto/proj/.env"
    assert action == "added"

    # unchanged content is detected
    _, action = envtools.push(v, key, env_file, cwd=repo)
    assert action == "unchanged"

    # changed content updates the entry
    env_file.write_text("API_KEY=rotated\n")
    _, action = envtools.push(v, key, env_file, cwd=repo)
    assert action == "updated"

    # fresh clone: restore
    env_file.unlink()
    results = envtools.pull(v, key, cwd=repo)
    assert results == [(".env", "restored")]
    assert env_file.read_text() == "API_KEY=rotated\n"
    assert env_file.stat().st_mode & 0o777 == 0o600

    # identical local file
    assert envtools.pull(v, key, cwd=repo) == [(".env", "unchanged")]

    # differing local file is protected unless forced
    env_file.write_text("LOCAL_EDIT=1\n")
    assert envtools.pull(v, key, cwd=repo) == [(".env", "skipped")]
    assert envtools.pull(v, key, cwd=repo, force=True) == [(".env", "restored")]
    assert env_file.read_text() == "API_KEY=rotated\n"


@requires_git
def test_nested_env_file(vault, tmp_path):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:a/b.git")
    nested = repo / "services" / "api" / ".env.production"
    nested.parent.mkdir(parents=True)
    nested.write_text("X=1\n")

    name, _ = envtools.push(v, key, nested, cwd=repo)
    assert name == "env/github.com/a/b/services/api/.env.production"

    nested.unlink()
    results = envtools.pull(v, key, cwd=repo)
    assert results == [("services/api/.env.production", "restored")]
    assert nested.read_text() == "X=1\n"


@requires_git
def test_pull_with_explicit_slug(vault, tmp_path):
    """Restore another repo's env file from anywhere."""
    v, key = vault
    src = make_git_repo(tmp_path / "src", origin="git@github.com:a/src.git")
    (src / ".env").write_text("S=1\n")
    envtools.push(v, key, src / ".env", cwd=src)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    results = envtools.pull(v, key, cwd=elsewhere, slug="github.com/a/src")
    assert results == [(".env", "restored")]
    assert (elsewhere / ".env").read_text() == "S=1\n"


def test_push_missing_file(vault, tmp_path):
    v, key = vault
    with pytest.raises(envtools.EnvError):
        envtools.push(v, key, tmp_path / "does-not-exist", cwd=tmp_path)


def test_list_all(vault, tmp_path):
    v, key = vault
    from tupacs.vault import new_entry

    v.write(key, "env/github.com/a/b/.env", new_entry("env", {"content": "X=1\n"}))
    assert envtools.list_all(v) == ["github.com/a/b/.env"]
