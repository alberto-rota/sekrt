import pytest

from sekrt import envtools
from sekrt.envtools import normalize_remote_url

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
    from sekrt.vault import new_entry

    v.write(key, "env/github.com/a/b/.env", new_entry("env", {"content": "X=1\n"}))
    assert envtools.list_all(v) == ["github.com/a/b/.env"]


def _set_origin(repo, url):
    import subprocess

    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", url], check=True)


def test_resolve_slug_follows_aliases(vault):
    v, _ = vault
    v.set_env_aliases({"github.com/you/old": "github.com/you/new"})
    assert envtools.resolve_slug(v, "github.com/you/old") == "github.com/you/new"
    assert envtools.resolve_slug(v, "github.com/you/new") == "github.com/you/new"


@requires_git
def test_adopt_moves_files_and_aliases(vault, tmp_path):
    v, key = vault
    old = make_git_repo(tmp_path / "proj", origin="git@github.com:you/old.git")
    (old / ".env").write_text("A=1\n")
    nested = old / "apps" / "api" / ".env"
    nested.parent.mkdir(parents=True)
    nested.write_text("B=2\n")
    envtools.push(v, key, old / ".env", cwd=old)
    envtools.push(v, key, nested, cwd=old)

    notice = envtools.adopt(v, key, "github.com/you/old", "github.com/you/new")
    assert notice is not None
    assert "github.com/you/old is now github.com/you/new" in notice
    assert v.exists("env/github.com/you/new/.env")
    assert v.exists("env/github.com/you/new/apps/api/.env")
    assert not v.exists("env/github.com/you/old/.env")
    assert v.read(key, "env/github.com/you/new/.env")["data"]["slug"] == "github.com/you/new"
    assert envtools.resolve_slug(v, "github.com/you/old") == "github.com/you/new"
    assert envtools.stored_files(v, "github.com/you/old") == [
        ".env",
        "apps/api/.env",
    ]


@requires_git
def test_push_after_rename_updates_one_identity(vault, tmp_path, monkeypatch):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:you/old.git")
    env_file = repo / ".env"
    env_file.write_text("A=1\n")
    envtools.push(v, key, env_file, cwd=repo)

    _set_origin(repo, "git@github.com:you/new.git")
    env_file.write_text("A=2\n")
    monkeypatch.setattr(envtools, "find_renamed_slug", lambda *a, **k: "github.com/you/old")

    name, action = envtools.push(v, key, env_file, cwd=repo)
    assert name == "env/github.com/you/new/.env"
    assert action == "updated"
    assert not v.exists("env/github.com/you/old/.env")
    assert v.read(key, name)["data"]["content"] == "A=2\n"
    assert envtools.resolve_slug(v, "github.com/you/old") == "github.com/you/new"


@requires_git
def test_pull_after_rename_restores(vault, tmp_path, monkeypatch):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:you/old.git")
    (repo / ".env").write_text("A=1\n")
    envtools.push(v, key, repo / ".env", cwd=repo)
    (repo / ".env").unlink()
    _set_origin(repo, "git@github.com:you/new.git")
    monkeypatch.setattr(envtools, "find_renamed_slug", lambda *a, **k: "github.com/you/old")

    assert envtools.pull(v, key, cwd=repo) == [(".env", "restored")]
    assert (repo / ".env").read_text() == "A=1\n"
    assert v.exists("env/github.com/you/new/.env")
    assert not v.exists("env/github.com/you/old/.env")


@requires_git
def test_old_origin_still_pulls_after_adopt(vault, tmp_path, monkeypatch):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:you/old.git")
    (repo / ".env").write_text("A=1\n")
    envtools.push(v, key, repo / ".env", cwd=repo)
    _set_origin(repo, "git@github.com:you/new.git")
    monkeypatch.setattr(envtools, "find_renamed_slug", lambda *a, **k: "github.com/you/old")
    envtools.realign(v, key, cwd=repo)

    stale = make_git_repo(tmp_path / "stale", origin="git@github.com:you/old.git")
    assert envtools.pull(v, key, cwd=stale) == [(".env", "restored")]
    assert (stale / ".env").read_text() == "A=1\n"


@requires_git
def test_explicit_repo_does_not_adopt(vault, tmp_path, monkeypatch):
    v, key = vault
    src = make_git_repo(tmp_path / "src", origin="git@github.com:upstream/proj.git")
    (src / ".env").write_text("UP=1\n")
    envtools.push(v, key, src / ".env", cwd=src)
    fork = make_git_repo(tmp_path / "fork", origin="git@github.com:me/proj.git")
    called = []

    def boom(*args, **kwargs):
        called.append(True)
        raise AssertionError("must not probe on --repo")

    monkeypatch.setattr(envtools, "find_renamed_slug", boom)
    results = envtools.pull(v, key, cwd=fork, slug="github.com/upstream/proj")
    assert results == [(".env", "restored")]
    assert not called
    assert v.exists("env/github.com/upstream/proj/.env")
    assert not v.exists("env/github.com/me/proj/.env")


def test_find_renamed_slug_redirect(vault, monkeypatch):
    v, key = vault
    from sekrt.vault import new_entry

    v.write(
        key,
        "env/github.com/you/old/.env",
        new_entry("env", {"content": "X=1\n", "slug": "github.com/you/old"}),
    )
    monkeypatch.setattr(
        envtools,
        "_follow_redirect_slug",
        lambda s: "github.com/you/new" if s == "github.com/you/old" else s,
    )
    monkeypatch.setattr(envtools, "_remote_head", lambda url: None)
    assert envtools.find_renamed_slug(v, key, "github.com/you/new") == "github.com/you/old"


def test_find_renamed_slug_same_owner_head(vault, monkeypatch):
    v, key = vault
    from sekrt.vault import new_entry

    v.write(
        key,
        "env/github.com/you/old/.env",
        new_entry("env", {"content": "X=1\n", "slug": "github.com/you/old"}),
    )
    monkeypatch.setattr(envtools, "_follow_redirect_slug", lambda s: None)
    monkeypatch.setattr(envtools, "_remote_head", lambda url: "abc123")
    assert envtools.find_renamed_slug(v, key, "github.com/you/new") == "github.com/you/old"


def test_find_renamed_slug_ignores_fork(vault, monkeypatch):
    v, key = vault
    from sekrt.vault import new_entry

    v.write(
        key,
        "env/github.com/upstream/proj/.env",
        new_entry("env", {"content": "X=1\n", "slug": "github.com/upstream/proj"}),
    )
    monkeypatch.setattr(envtools, "_follow_redirect_slug", lambda s: None)
    monkeypatch.setattr(envtools, "_remote_head", lambda url: "abc123")
    assert envtools.find_renamed_slug(v, key, "github.com/me/proj") is None


def test_find_renamed_slug_skips_local(vault, monkeypatch):
    v, key = vault
    from sekrt.vault import new_entry

    v.write(
        key,
        "env/local/proj/.env",
        new_entry("env", {"content": "X=1\n", "slug": "local/proj"}),
    )
    monkeypatch.setattr(envtools, "_follow_redirect_slug", lambda s: "github.com/you/proj")
    assert envtools.find_renamed_slug(v, key, "github.com/you/proj") is None
