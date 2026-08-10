import subprocess

from sekrt.cli import main
from sekrt.generate import generate_password

from .conftest import PASSPHRASE, make_git_repo, requires_git


def invoke(runner, *args, **kwargs):
    result = runner.invoke(main, args, catch_exceptions=False, **kwargs)
    return result


def test_init_and_status(runner, vault_dir):
    result = invoke(runner, "init")
    assert result.exit_code == 0
    assert "vault created" in result.output

    result = invoke(runner, "status")
    assert result.exit_code == 0
    assert "entries   0" in result.output


def test_init_twice_fails(runner, vault_dir):
    invoke(runner, "init")
    result = runner.invoke(main, ["init"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_add_get_show_roundtrip(runner, vault_dir):
    invoke(runner, "init")
    result = invoke(runner, "add", "work/github", "-u", "alberto", input="s3cret!\ns3cret!\n")
    assert result.exit_code == 0

    result = invoke(runner, "get", "work/github")
    assert result.output.strip() == "s3cret!"

    result = invoke(runner, "get", "work/github", "--field", "username")
    assert result.output.strip() == "alberto"

    result = invoke(runner, "show", "work/github")
    assert "********" in result.output
    assert "s3cret!" not in result.output

    result = invoke(runner, "show", "work/github", "--reveal")
    assert "s3cret!" in result.output


def test_show_masks_note_by_default(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "wifi/office", "-t", "note", "--notes", "WPA2 s3cr3t-phrase")

    result = invoke(runner, "show", "wifi/office")
    assert "s3cr3t-phrase" not in result.output

    result = invoke(runner, "show", "wifi/office", "--reveal")
    assert "s3cr3t-phrase" in result.output


def test_show_strips_terminal_control_chars(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "evil", "-t", "note", "--notes", "safe\x1b[2J\x07text")

    result = invoke(runner, "show", "evil", "--reveal")
    assert "\x1b" not in result.output
    assert "\x07" not in result.output
    assert "safe[2Jtext" in result.output


def test_add_generate(runner, vault_dir):
    invoke(runner, "init")
    result = invoke(runner, "add", "gen/entry", "-g", "--show", "-L", "24")
    assert result.exit_code == 0
    secret = invoke(runner, "get", "gen/entry").output.strip()
    assert len(secret) == 24


def test_get_suggests_close_matches(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "work/github", "-g")
    result = runner.invoke(main, ["get", "work/gihub"])
    assert result.exit_code != 0
    assert "work/github" in result.output


def test_ls_find_mv_rm(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "a/one", "-g")
    invoke(runner, "add", "b/two", "-g")

    assert invoke(runner, "ls").output.splitlines() == ["a/one", "b/two"]
    assert invoke(runner, "ls", "b/").output.splitlines() == ["b/two"]
    assert invoke(runner, "find", "two").output.strip() == "b/two"

    invoke(runner, "mv", "a/one", "c/three")
    assert invoke(runner, "ls").output.splitlines() == ["b/two", "c/three"]

    invoke(runner, "rm", "c/three", "-f")
    assert invoke(runner, "ls").output.splitlines() == ["b/two"]


def test_aliases(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "insert", "x", "-g")  # pass-style alias for add
    assert invoke(runner, "list").output.strip() == "x"


def test_generate_command(runner):
    result = invoke(runner, "generate", "32", "--no-symbols")
    secret = result.output.strip()
    assert len(secret) == 32
    assert secret.isalnum()


def test_generate_password_properties():
    for _ in range(20):
        p = generate_password(12)
        assert any(c.islower() for c in p)
        assert any(c.isupper() for c in p)
        assert any(c.isdigit() for c in p)


def test_unlock_lock_cycle(runner, vault_dir, monkeypatch):
    invoke(runner, "init")
    result = invoke(runner, "unlock", "-t", "5")
    assert result.exit_code == 0

    # cached key works even without the passphrase env var
    monkeypatch.delenv("SEKRT_PASSPHRASE")
    invoke(runner, "add", "cached/entry", "-g")
    assert invoke(runner, "get", "cached/entry").exit_code == 0

    invoke(runner, "lock")
    assert "locked" in invoke(runner, "status").output


def test_passwd(runner, vault_dir, monkeypatch):
    invoke(runner, "init")
    invoke(runner, "add", "keep", "-g")
    old_secret = invoke(runner, "get", "keep").output.strip()

    monkeypatch.delenv("SEKRT_PASSPHRASE")
    result = invoke(
        runner, "passwd", input=f"{PASSPHRASE}\nnew phrase\nnew phrase\n"
    )
    assert result.exit_code == 0

    monkeypatch.setenv("SEKRT_PASSPHRASE", "new phrase")
    assert invoke(runner, "get", "keep").output.strip() == old_secret


def test_wrong_passphrase_env(runner, vault_dir, monkeypatch):
    invoke(runner, "init")
    monkeypatch.setenv("SEKRT_PASSPHRASE", "wrong")
    result = runner.invoke(main, ["add", "x", "-g"])
    assert result.exit_code != 0
    assert "wrong passphrase" in result.output


@requires_git
def test_env_workflow(runner, vault_dir, tmp_path, monkeypatch):
    invoke(runner, "init")
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:me/proj.git")
    (repo / ".env").write_text("TOKEN=t0ps3cret\n")
    monkeypatch.chdir(repo)

    result = invoke(runner, "env", "push")
    assert "added" in result.output

    result = invoke(runner, "env", "ls")
    assert "* github.com/me/proj/.env" in result.output

    (repo / ".env").unlink()
    result = invoke(runner, "env", "pull")
    assert "restored" in result.output
    assert (repo / ".env").read_text() == "TOKEN=t0ps3cret\n"

    assert invoke(runner, "env", "show").output == "TOKEN=t0ps3cret\n"


@requires_git
def test_sync_workflow(runner, vault_dir, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    invoke(runner, "init", "--remote", str(bare))
    invoke(runner, "add", "synced", "-g")
    result = invoke(runner, "sync")
    assert result.exit_code == 0
    assert "synced" in result.output


def test_ssh_workflow(runner, vault_dir, tmp_path):
    invoke(runner, "init")
    result = invoke(runner, "ssh", "add", "deploy", "--generate")
    assert result.exit_code == 0
    assert "ssh-ed25519" in result.output

    assert invoke(runner, "ssh", "ls").output.strip() == "deploy"

    pub = invoke(runner, "ssh", "pub", "deploy").output
    assert pub.startswith("ssh-ed25519 ")

    dest = tmp_path / "sshdir"
    result = invoke(runner, "ssh", "restore", "deploy", "--dir", str(dest))
    assert result.exit_code == 0
    assert (dest / "deploy").stat().st_mode & 0o777 == 0o600


def test_no_vault_errors_cleanly(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("SEKRT_VAULT", str(tmp_path / "missing"))
    result = runner.invoke(main, ["ls"])
    assert result.exit_code != 0
    assert "sekrt init" in result.output


def test_file_workflow(runner, vault_dir, tmp_path, monkeypatch):
    invoke(runner, "init")
    content = b"code-1\ncode-2\ncode-3\n"
    src = tmp_path / "recovery-codes.txt"
    src.write_bytes(content)

    result = invoke(runner, "file", "add", "mfa/github", str(src))
    assert result.exit_code == 0
    assert "file/mfa/github" in result.output

    assert invoke(runner, "file", "ls").output.strip() == "mfa/github"

    shown = invoke(runner, "show", "file/mfa/github").output
    assert "content_b64" not in shown
    assert "use `sekrt file get" in shown

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = invoke(runner, "file", "get", "mfa/github")
    assert result.exit_code == 0
    dest = workdir / "recovery-codes.txt"
    assert dest.read_bytes() == content

    result = runner.invoke(main, ["file", "get", "mfa/github"])
    assert result.exit_code != 0  # refuses to overwrite without --force

    out = tmp_path / "restored.txt"
    result = invoke(runner, "file", "get", "mfa/github", "-o", str(out))
    assert result.exit_code == 0
    assert out.read_bytes() == content


def test_edit_note_is_raw_multiline(runner, vault_dir, monkeypatch):
    invoke(runner, "init")
    invoke(runner, "add", "wifi/office", "-t", "note", "--notes", "line one")

    seen = {}

    def fake_edit_text(initial, *, suffix=".json"):
        seen["initial"] = initial
        seen["suffix"] = suffix
        return "line one\nline two\nline three\n"

    monkeypatch.setattr("sekrt.cli.edit_text", fake_edit_text)
    result = invoke(runner, "edit", "wifi/office")
    assert result.exit_code == 0

    # the editor was handed the raw note text, not a JSON-escaped blob
    assert seen["initial"] == "line one"
    assert seen["suffix"] == ".txt"

    shown = invoke(runner, "show", "wifi/office", "--reveal").output
    assert "line one" in shown and "line two" in shown and "line three" in shown
