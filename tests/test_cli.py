import os
import subprocess
import sys
from pathlib import Path

import pytest

from sekrt.cli import main
from sekrt.generate import generate_password

from .conftest import PASSPHRASE, make_git_repo, make_pushed_vault, requires_git


class _Tty:
    """Stand-in for an interactive stdin, so `init` takes its prompting path."""

    def isatty(self):
        return True


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


def test_show_reveal_puts_the_secret_alone_on_its_own_line(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "work/github", "-u", "alberto", input="s3cret!\ns3cret!\n")

    lines = invoke(runner, "show", "work/github", "--reveal").output.splitlines()
    assert "  username: alberto" in lines
    assert lines[-1] == "s3cret!"  # last, unindented, nothing sharing the line


def test_show_reveal_keeps_multiline_secrets_verbatim(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "wifi/office", "-t", "note", "--notes", "line one\n  line two")

    lines = invoke(runner, "show", "wifi/office", "--reveal").output.splitlines()
    assert lines[-2:] == ["line one", "  line two"]


def test_show_reveal_never_prompts_without_a_terminal(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "work/github", "-g")

    result = invoke(runner, "show", "work/github", "--reveal")
    assert "press c" not in result.output + result.stderr


@pytest.fixture
def fake_clipboard(monkeypatch):
    """A recording clipboard at a pretend terminal, so `press c` can be tested."""
    from sekrt import cli, clipboard

    copied = []
    monkeypatch.setattr(cli, "_at_terminal", lambda: True)
    monkeypatch.setattr(clipboard, "available", lambda: True)
    monkeypatch.setattr(clipboard, "copy", lambda value, *a, **kw: copied.append(value))
    return copied


@pytest.mark.parametrize("key, expected", [("c", ["s3cret!"]), ("C", ["s3cret!"]), ("\x1b", [])])
def test_show_reveal_copies_on_c(runner, vault_dir, fake_clipboard, monkeypatch, key, expected):
    from sekrt import clipboard

    monkeypatch.setattr(clipboard, "read_key", lambda: key)
    invoke(runner, "init")
    invoke(runner, "add", "work/github", input="s3cret!\ns3cret!\n")

    result = invoke(runner, "show", "work/github", "--reveal")
    assert fake_clipboard == expected
    assert "press c to copy password" in result.stderr
    assert "s3cret!" not in result.stderr  # the prompt never repeats the secret
    assert ("copied to clipboard" in result.stderr) is bool(expected)


def test_show_reveal_copies_the_primary_secret(runner, vault_dir, fake_clipboard, monkeypatch):
    from sekrt import clipboard

    monkeypatch.setattr(clipboard, "read_key", lambda: "c")
    invoke(runner, "init")
    invoke(runner, "add", "cloud/key", "-t", "api_key", "--notes", "n0tes",
           input="k3y-value\nk3y-value\n")

    invoke(runner, "show", "cloud/key", "--reveal")
    assert fake_clipboard == ["k3y-value"]  # the key, not the (also secret) notes


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


@pytest.fixture
def fake_picker(monkeypatch):
    """Pretend there's a terminal, and record what the picker was asked to show."""
    from sekrt.tui import picker

    calls = []

    def fake_pick(names, *, query="", action="select"):
        calls.append({"names": names, "query": query, "action": action})
        return names[0] if names else None

    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(picker, "pick", fake_pick)
    return calls


def test_get_without_a_name_picks_interactively(runner, vault_dir, fake_picker):
    invoke(runner, "init")
    invoke(runner, "add", "cloud/aws-key", "-g")
    invoke(runner, "add", "work/github", "-g")

    result = invoke(runner, "get")
    assert result.exit_code == 0
    assert fake_picker[0]["names"] == ["cloud/aws-key", "work/github"]
    assert fake_picker[0]["query"] == ""
    assert result.output.strip() == invoke(runner, "get", "cloud/aws-key").output.strip()


def test_passphrase_is_asked_before_the_picker_draws(runner, vault_dir, monkeypatch):
    """Unlock first: a list you can act on beats one that prompts after you choose."""
    from sekrt import cli
    from sekrt.tui import picker

    invoke(runner, "init")
    invoke(runner, "add", "cloud/aws-key", "-g")

    order = []
    unlock = cli.obtain_key

    def record_unlock(vault):
        order.append("unlock")
        return unlock(vault)

    def record_pick(names, **kwargs):
        order.append("pick")
        return names[0]

    monkeypatch.setattr(cli, "obtain_key", record_unlock)
    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(picker, "pick", record_pick)

    assert invoke(runner, "get").exit_code == 0
    assert order == ["unlock", "pick"]


def test_partial_name_seeds_the_picker_filter(runner, vault_dir, fake_picker):
    invoke(runner, "init")
    invoke(runner, "add", "cloud/aws-key", "-g")

    result = invoke(runner, "show", "aws")
    assert result.exit_code == 0
    assert fake_picker[0]["query"] == "aws"
    assert "cloud/aws-key" in result.output


def test_exact_names_never_open_the_picker(runner, vault_dir, fake_picker):
    invoke(runner, "init")
    invoke(runner, "add", "cloud/aws-key", "-g")

    assert invoke(runner, "show", "cloud/aws-key").exit_code == 0
    assert fake_picker == []


def test_cancelling_the_picker_aborts(runner, vault_dir, monkeypatch):
    from sekrt.tui import picker

    invoke(runner, "init")
    invoke(runner, "add", "cloud/aws-key", "-g")
    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(picker, "pick", lambda *a, **kw: None)

    result = runner.invoke(main, ["get"])
    assert result.exit_code != 0
    assert "cloud/aws-key" not in result.output  # nothing decrypted


def test_get_without_a_name_fails_when_not_a_terminal(runner, vault_dir):
    invoke(runner, "init")
    invoke(runner, "add", "work/github", "-g")
    result = runner.invoke(main, ["get"])
    assert result.exit_code != 0
    assert "NAME is required" in result.output


def test_picker_refuses_an_empty_vault(runner, vault_dir, fake_picker):
    invoke(runner, "init")
    result = runner.invoke(main, ["get"])
    assert result.exit_code != 0
    assert "vault is empty" in result.output


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


def test_the_unlock_prompt_names_a_vault_only_when_sekrt_vault_points_at_one(
    vault_dir, monkeypatch
):
    from sekrt.cli import unlock_prompt
    from sekrt.prefs import DEFAULT_PALETTE
    from sekrt.vault import Vault

    prompt = unlock_prompt(Vault(vault_dir), DEFAULT_PALETTE)
    assert "🔐" in prompt and "passphrase" in prompt and "❯" in prompt
    assert vault_dir.name in prompt  # $SEKRT_VAULT points at a scratch vault

    monkeypatch.delenv("SEKRT_VAULT")
    assert vault_dir.name not in unlock_prompt(Vault(vault_dir), DEFAULT_PALETTE)


def test_the_unlock_prompt_carries_no_escapes_without_a_terminal(vault_dir):
    from sekrt.cli import unlock_prompt
    from sekrt.prefs import DEFAULT_PALETTE
    from sekrt.vault import Vault

    assert "\x1b" not in unlock_prompt(Vault(vault_dir), DEFAULT_PALETTE)


def test_a_wrong_passphrase_counts_down_the_tries(runner, vault_dir, monkeypatch):
    invoke(runner, "init")
    invoke(runner, "add", "work/github", "-g")
    monkeypatch.delenv("SEKRT_PASSPHRASE")

    result = runner.invoke(main, ["get", "work/github"], input="nope\nnope\nnope\n")
    assert result.exit_code != 0
    assert "2 tries left" in result.stderr
    assert "1 try left" in result.stderr
    assert "wrong passphrase (3 attempts)" in result.output


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


@requires_git
def test_clone_sets_up_a_second_machine(runner, tmp_path, monkeypatch):
    """The new-machine path: one command, no manual git."""
    bare, _, _ = make_pushed_vault(tmp_path, [("api/token", "s3cret")])

    # Machine 2: `sekrt clone` and nothing else.
    dest = tmp_path / "machine2"
    monkeypatch.setenv("SEKRT_VAULT", str(dest))
    result = runner.invoke(main, ["clone", bare])
    assert result.exit_code == 0, result.output
    assert "1 entry available" in result.output

    listed = runner.invoke(main, ["ls"])
    assert "api/token" in listed.output


@requires_git
def test_clone_rejects_a_repo_that_is_not_a_vault(runner, tmp_path, monkeypatch):
    source = tmp_path / "not-a-vault"
    source.mkdir()
    (source / "README.md").write_text("hello")
    subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(source), "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "init",
        ],
        check=True,
    )

    dest = tmp_path / "machine2"
    monkeypatch.setenv("SEKRT_VAULT", str(dest))
    result = runner.invoke(main, ["clone", str(source)])
    assert result.exit_code != 0
    assert "does not look like a sekrt vault" in result.output
    assert not dest.exists()  # debris cleaned up


@requires_git
def test_init_refuses_a_remote_that_already_has_a_vault(runner, tmp_path, monkeypatch):
    """The trap that caused the unmergeable rebase."""
    bare, _, _ = make_pushed_vault(tmp_path)

    monkeypatch.setenv("SEKRT_VAULT", str(tmp_path / "machine2"))
    result = runner.invoke(main, ["init", "--remote", bare])
    assert result.exit_code != 0
    assert "already contains a vault" in result.output
    assert "sekrt clone" in result.output
    assert not (tmp_path / "machine2" / ".sekrt.json").exists()


@requires_git
def test_init_offers_to_clone_when_interactive(runner, tmp_path, monkeypatch):
    """`init` on a second machine: answering yes clones instead of creating."""
    bare, _, _ = make_pushed_vault(tmp_path, [("api/token", "s3cret")])
    monkeypatch.setenv("SEKRT_VAULT", str(tmp_path / "machine2"))
    monkeypatch.setattr("click.get_text_stream", lambda *_, **__: _Tty())

    result = runner.invoke(main, ["init"], input=f"y\n{bare}\n")
    assert result.exit_code == 0, result.output
    assert "vault cloned" in result.output
    assert "1 entry available" in result.output
    assert "api/token" in runner.invoke(main, ["ls"]).output


@requires_git
def test_init_creates_when_user_says_no(runner, vault_dir, monkeypatch):
    monkeypatch.setattr("click.get_text_stream", lambda *_, **__: _Tty())
    result = runner.invoke(main, ["init"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "vault created" in result.output


def test_init_does_not_prompt_when_not_a_tty(runner, vault_dir):
    """Scripts and CI must keep working without an interactive answer."""
    result = invoke(runner, "init")
    assert result.exit_code == 0
    assert "vault created" in result.output
    assert "already have" not in result.output


# --------------------------------------------------------------------------- run / shell


@pytest.fixture
def fake_launch(monkeypatch):
    """Record what would have been exec'd instead of replacing the test process."""
    from sekrt import runtools

    calls = []

    def launch(argv, env):
        calls.append({"argv": list(argv), "env": dict(env)})
        return 0

    monkeypatch.setattr(runtools, "launch", launch)
    return calls


@pytest.fixture
def token_vault(runner, vault_dir):
    """A vault holding one API key, `api/my-token`, worth $MY_TOKEN."""
    invoke(runner, "init")
    invoke(runner, "add", "api/my-token", "-t", "api_key", input="t0ps3cret\nt0ps3cret\n")
    return vault_dir


def test_run_puts_a_named_secret_in_the_commands_environment(
    runner, token_vault, fake_launch
):
    result = invoke(
        runner, "run", "-e", "MY_TOKEN", "--no-env-files", "--", "service", "log"
    )
    assert result.exit_code == 0
    assert fake_launch[0]["argv"] == ["service", "log"]
    assert fake_launch[0]["env"]["MY_TOKEN"] == "t0ps3cret"
    assert "SEKRT_PASSPHRASE" not in fake_launch[0]["env"]  # never handed on


def test_run_can_be_told_which_entry_a_variable_comes_from(runner, token_vault, fake_launch):
    invoke(runner, "add", "work/github", input="hunter2\nhunter2\n")
    result = invoke(
        runner, "run", "-e", "GH=work/github", "--no-env-files", "--", "service"
    )
    assert result.exit_code == 0
    assert fake_launch[0]["env"]["GH"] == "hunter2"


def test_run_with_c_resolves_what_the_command_refers_to_and_hands_it_to_a_shell(
    runner, token_vault, fake_launch, monkeypatch
):
    monkeypatch.setenv("SHELL", "/bin/sh")
    command = 'service log --token="$MY_TOKEN"'
    result = invoke(runner, "run", "--no-env-files", "-c", command)
    assert result.exit_code == 0
    assert fake_launch[0]["argv"] == ["/bin/sh", "-c", command]
    assert fake_launch[0]["env"]["MY_TOKEN"] == "t0ps3cret"


def test_run_notices_when_the_calling_shell_already_ate_the_reference(
    runner, token_vault, fake_launch
):
    """`-c "echo $MY_TOKEN"` in double quotes arrives as `echo ` — say so."""
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--no-env-files", "-c", "echo ")
    assert result.exit_code == 0
    assert "double quotes" in result.stderr
    assert "Single-quote it" in result.stderr


def test_run_says_nothing_when_the_reference_survived_the_quoting(
    runner, token_vault, fake_launch
):
    result = invoke(runner, "run", "--no-env-files", "-c", "echo $MY_TOKEN")
    assert result.exit_code == 0
    assert "double quotes" not in result.stderr


def test_a_c_string_with_its_own_dollars_is_left_alone(runner, token_vault, fake_launch):
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--no-env-files", "-c", "echo $$")
    assert result.exit_code == 0
    assert "double quotes" not in result.stderr  # a `$` of some kind is still there


def test_run_notes_a_reference_the_vault_cannot_answer_but_still_runs(
    runner, token_vault, fake_launch
):
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--no-env-files", "-c", "svc $MY_TOKN")
    assert result.exit_code == 0  # the shell may well have its own $MY_TOKN
    assert "MY_TOKN" in result.stderr
    assert "MY_TOKEN" in result.stderr  # ...and the typo is spelled out for you
    assert fake_launch  # ran anyway


def test_run_warns_when_a_quoted_reference_reached_the_command_as_text(
    runner, token_vault, fake_launch
):
    result = invoke(
        runner, "run", "-e", "MY_TOKEN", "--no-env-files", "--", "svc", "--token=$MY_TOKEN"
    )
    assert result.exit_code == 0
    assert "reached the command as text" in result.stderr
    assert "sekrt run -c" in result.stderr
    assert "t0ps3cret" not in result.stderr  # the warning never repeats the secret


def test_run_does_not_warn_when_the_command_is_a_shell_that_will_expand_it(
    runner, token_vault, fake_launch
):
    result = invoke(
        runner, "run", "-e", "MY_TOKEN", "--no-env-files", "--", "sh", "-c", "svc $MY_TOKEN"
    )
    assert result.exit_code == 0
    assert "as text" not in result.stderr


def test_run_notices_an_argument_the_calling_shell_ate(runner, token_vault, fake_launch):
    """`-- svc --token=$MY_TOKEN` unset outside arrives as `--token=`."""
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--", "svc", "--token=")
    assert result.exit_code == 0
    assert "expanded" in result.stderr
    assert "printenv" in result.stderr
    assert "t0ps3cret" not in result.stderr


def test_run_says_nothing_about_an_ordinary_command_line(runner, token_vault, fake_launch):
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--", "svc", "--token=abc", "start")
    assert result.exit_code == 0
    assert result.stderr == ""


def test_run_never_writes_a_secret_into_the_command_line(runner, token_vault, fake_launch):
    invoke(runner, "run", "-e", "MY_TOKEN", "--no-env-files", "--", "svc", "--token=$MY_TOKEN")
    assert "t0ps3cret" not in " ".join(fake_launch[0]["argv"])


def test_run_passes_the_commands_exit_status_back(runner, token_vault, monkeypatch):
    from sekrt import runtools

    monkeypatch.setattr(runtools, "launch", lambda argv, env: 3)
    result = runner.invoke(
        main, ["run", "-e", "MY_TOKEN", "--no-env-files", "--", "false"]
    )
    assert result.exit_code == 3


def test_run_dry_run_lists_names_and_sources_but_no_values(runner, token_vault):
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--no-env-files", "-n", "--", "service")
    assert result.exit_code == 0
    assert "MY_TOKEN" in result.output
    assert "api/my-token:key" in result.output
    assert "t0ps3cret" not in result.output
    assert "would run: service" in result.output


def test_run_without_a_command_points_at_shell(runner, token_vault):
    result = runner.invoke(main, ["run", "-e", "MY_TOKEN"])
    assert result.exit_code != 0
    assert "sekrt shell" in result.output


def test_run_refuses_both_a_command_and_a_shell_string(runner, token_vault):
    result = runner.invoke(main, ["run", "-c", "echo hi", "--", "echo", "hi"])
    assert result.exit_code != 0
    assert "give a command to run" in result.output


def test_run_with_nothing_to_expose_says_so_without_asking_for_the_passphrase(
    runner, vault_dir, monkeypatch
):
    invoke(runner, "init")  # an empty vault: nothing a variable could carry
    monkeypatch.delenv("SEKRT_PASSPHRASE")
    result = runner.invoke(main, ["run", "--", "service"])
    assert result.exit_code != 0
    assert "nothing to expose" in result.output
    assert "sekrt env push" in result.output
    assert "passphrase" not in (result.output + result.stderr).lower()


def test_run_with_nothing_named_exposes_every_password_and_api_key(
    runner, token_vault, fake_launch
):
    invoke(runner, "add", "work/github", input="hunter2\nhunter2\n")
    result = invoke(runner, "run", "--", "service")
    assert result.exit_code == 0
    env = fake_launch[0]["env"]
    assert env["MY_TOKEN"] == "t0ps3cret"
    assert env["GITHUB"] == "hunter2"


def test_naming_a_variable_hands_over_that_one_and_not_the_vault(
    runner, token_vault, fake_launch
):
    invoke(runner, "add", "work/github", input="hunter2\nhunter2\n")
    result = invoke(runner, "run", "-e", "MY_TOKEN", "--", "service")
    assert result.exit_code == 0
    assert fake_launch[0]["env"]["MY_TOKEN"] == "t0ps3cret"
    assert "GITHUB" not in fake_launch[0]["env"]


def test_run_leaves_out_notes_ssh_keys_and_stored_files(
    runner, token_vault, tmp_path, fake_launch
):
    invoke(runner, "add", "notes/wifi", "-t", "note", "--notes", "WPA2 phrase")
    invoke(runner, "ssh", "add", "deploy", "--generate")
    blob = tmp_path / "codes.txt"
    blob.write_text("1\n2\n")
    invoke(runner, "file", "add", "mfa/codes", str(blob))

    assert invoke(runner, "run", "--", "service").exit_code == 0
    assert set(fake_launch[0]["env"]["SEKRT_EXPOSED"].split()) == {"MY_TOKEN"}


def test_run_notes_a_variable_two_entries_both_answer_to(runner, vault_dir, fake_launch):
    invoke(runner, "init")
    invoke(runner, "add", "a/token", "-t", "api_key", input="one\none\n")
    invoke(runner, "add", "b/token", "-t", "api_key", input="two\ntwo\n")
    invoke(runner, "add", "api/my-token", "-t", "api_key", input="fine\nfine\n")

    result = invoke(runner, "run", "--", "service")
    assert result.exit_code == 0
    assert "$TOKEN left unset" in result.stderr
    assert "-e TOKEN=a/token" in result.stderr
    assert "TOKEN" not in fake_launch[0]["env"]
    assert fake_launch[0]["env"]["MY_TOKEN"] == "fine"  # the rest is unaffected


@requires_git
def test_run_exposes_the_repos_stored_env_file_by_default(
    runner, vault_dir, tmp_path, monkeypatch, fake_launch
):
    invoke(runner, "init")
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:me/proj.git")
    (repo / ".env").write_text("DATABASE_URL=postgres://local\nTOKEN=t0ps3cret\n")
    monkeypatch.chdir(repo)
    invoke(runner, "env", "push")

    result = invoke(runner, "run", "--", "npm", "start")
    assert result.exit_code == 0
    env = fake_launch[0]["env"]
    assert env["DATABASE_URL"] == "postgres://local"
    assert env["TOKEN"] == "t0ps3cret"
    assert env["SEKRT_EXPOSED"] == "DATABASE_URL TOKEN"


def test_shell_opens_a_subshell_holding_the_secrets(
    runner, token_vault, fake_launch, monkeypatch
):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    result = invoke(runner, "shell", "-e", "MY_TOKEN", "--no-env-files")
    assert result.exit_code == 0
    assert fake_launch[0]["argv"] == ["/bin/zsh", "-i"]
    assert fake_launch[0]["env"]["MY_TOKEN"] == "t0ps3cret"
    assert "MY_TOKEN" in result.stderr and "exit" in result.stderr
    assert "t0ps3cret" not in result.stderr
    # the prompt wiring rides along in the environment, and is announced
    assert Path(fake_launch[0]["env"]["ZDOTDIR"]).joinpath(".zshrc").is_file()
    assert "🔓" in result.stderr


def test_shell_dry_run_shows_the_bare_shell_and_writes_nothing(
    runner, token_vault, fake_launch, monkeypatch
):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    result = invoke(runner, "shell", "-e", "MY_TOKEN", "--no-env-files", "-n")
    assert result.exit_code == 0
    assert "would run: /bin/zsh" in result.output
    assert fake_launch == []


def test_exec_and_sh_are_aliases(runner, token_vault, fake_launch):
    assert invoke(runner, "exec", "-e", "MY_TOKEN", "--no-env-files", "--", "svc").exit_code == 0
    assert invoke(runner, "sh", "-e", "MY_TOKEN", "--no-env-files").exit_code == 0
    assert len(fake_launch) == 2


def test_run_really_hands_the_secret_to_a_real_process(runner, token_vault):
    """End to end, with an actual child: the value is in its environment, and
    the vault passphrase is not."""
    probe = (
        "import os; print(os.environ.get('MY_TOKEN')); "
        "print('leaked' if 'SEKRT_PASSPHRASE' in os.environ else 'no-passphrase')"
    )
    result = subprocess.run(
        [sys.executable, "-m", "sekrt", "run", "-e", "MY_TOKEN", "--no-env-files",
         "--", sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "SEKRT_VAULT": str(token_vault), "SEKRT_PASSPHRASE": PASSPHRASE},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["t0ps3cret", "no-passphrase"]


# --------------------------------------------------------------------------- inline forms


class _Form:
    """A stand-in for the inline form: records what it was asked, answers *answer*."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.answer: dict[str, str] = {}

    def fill(self, fields, *, title="", action="save"):
        self.calls.append({"fields": {f.key: f for f in fields}, "title": title})
        return dict(self.answer)


@pytest.fixture
def fake_form(monkeypatch):
    from sekrt.tui import form, picker

    fake = _Form()
    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(form, "fill", fake.fill)
    return fake


def test_add_without_a_name_opens_the_form(runner, vault_dir, fake_form):
    invoke(runner, "init")
    fake_form.answer = {
        "name": "work/github", "type": "password", "username": "alberto",
        "secret": "s3cret!", "url": "https://github.com", "notes": "",
    }
    result = invoke(runner, "add")
    assert result.exit_code == 0
    assert "stored work/github" in result.output
    assert invoke(runner, "get", "work/github").output.strip() == "s3cret!"
    assert invoke(runner, "get", "work/github", "-f", "username").output.strip() == "alberto"


def test_add_interactive_prefills_the_name_and_type(runner, vault_dir, fake_form):
    invoke(runner, "init")
    fake_form.answer = {
        "name": "cloud/aws-key", "type": "api_key", "username": "",
        "secret": "k3y", "url": "", "notes": "",
    }
    result = invoke(runner, "add", "cloud/aws-key", "-t", "api_key", "-i")
    assert result.exit_code == 0
    fields = fake_form.calls[0]["fields"]
    assert fields["name"].value == "cloud/aws-key"
    assert fields["type"].value == "api_key"
    assert "  key: ********" in invoke(runner, "show", "cloud/aws-key").output


def test_the_form_refuses_to_store_an_empty_secret(runner, vault_dir, fake_form):
    invoke(runner, "init")
    fake_form.answer = {
        "name": "empty", "type": "password", "username": "", "secret": "", "url": "", "notes": "",
    }
    result = runner.invoke(main, ["add"])
    assert result.exit_code != 0
    assert "empty secret" in result.output
    assert invoke(runner, "ls").output.startswith("(vault is empty")


def test_a_note_typed_into_the_form_needs_no_editor(runner, vault_dir, fake_form, monkeypatch):
    def no_editor(*args, **kwargs):
        raise AssertionError("$EDITOR should not open when the form already has the text")

    monkeypatch.setattr("sekrt.cli.edit_text", no_editor)
    invoke(runner, "init")
    fake_form.answer = {
        "name": "wifi/office", "type": "note", "username": "",
        "secret": "WPA2 s3cr3t-phrase", "url": "", "notes": "",
    }
    assert invoke(runner, "add").exit_code == 0
    assert "s3cr3t-phrase" in invoke(runner, "show", "wifi/office", "-r").output


def test_cancelling_the_form_stores_nothing(runner, vault_dir, monkeypatch):
    from sekrt.tui import form, picker

    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(form, "fill", lambda *a, **kw: None)
    invoke(runner, "init")
    result = runner.invoke(main, ["add"])
    assert result.exit_code != 0
    assert invoke(runner, "ls").output.startswith("(vault is empty")


def test_add_without_a_name_still_insists_on_one_without_a_terminal(runner, vault_dir):
    invoke(runner, "init")
    result = runner.invoke(main, ["add"])
    assert result.exit_code != 0
    assert "NAME is required" in result.output


def test_interactive_needs_a_terminal(runner, vault_dir):
    invoke(runner, "init")
    result = runner.invoke(main, ["add", "x", "-i"])
    assert result.exit_code != 0
    assert "needs a terminal" in result.output


def test_ssh_add_without_a_name_opens_the_form(runner, vault_dir, fake_form):
    invoke(runner, "init")
    fake_form.answer = {"name": "deploy", "source": "generate", "key": "", "comment": "ci"}
    result = invoke(runner, "ssh", "add")
    assert result.exit_code == 0
    assert "ssh-ed25519" in result.output
    assert invoke(runner, "ssh", "pub", "deploy").output.strip().endswith("ci")


def test_the_ssh_form_can_import_a_key_file(runner, vault_dir, tmp_path, fake_form):
    invoke(runner, "init")
    invoke(runner, "ssh", "add", "source-key", "--generate")
    written = tmp_path / "keys"
    invoke(runner, "ssh", "restore", "source-key", "--dir", str(written))

    fake_form.answer = {
        "name": "imported", "source": "import",
        "key": str(written / "source-key"), "comment": "",
    }
    result = invoke(runner, "ssh", "add")
    assert result.exit_code == 0, result.output
    assert "stored ssh/imported" in result.output


def test_the_ssh_form_needs_a_file_to_import(runner, vault_dir, fake_form):
    invoke(runner, "init")
    fake_form.answer = {"name": "x", "source": "import", "key": "", "comment": ""}
    result = runner.invoke(main, ["ssh", "add"])
    assert result.exit_code != 0
    assert "needs a key file" in result.output


# --------------------------------------------------------------------------- colors


def test_config_shows_the_stock_colors_without_a_terminal(runner):
    """No terminal to draw a panel on: print what is set instead."""
    result = invoke(runner, "config")
    assert result.exit_code == 0
    assert "#aaaaaa" in result.output and "#ff0000" in result.output
    assert "nothing saved yet" in result.output


def test_config_sets_one_color_and_keeps_the_others(runner):
    from sekrt.prefs import DEFAULT_PALETTE, load_palette

    result = invoke(runner, "config", "--accent", "#00d7af")
    assert result.exit_code == 0
    assert "colors saved" in result.output

    palette = load_palette()
    assert palette.accent == "#00d7af"
    assert palette.primary == DEFAULT_PALETTE.primary
    assert "#00d7af" in invoke(runner, "config", "--show").output


def test_config_accepts_color_names_and_bare_hex(runner):
    from sekrt.prefs import load_palette

    assert invoke(runner, "config", "--primary", "cyan", "--secondary", "5f6672").exit_code == 0
    palette = load_palette()
    assert (palette.primary, palette.secondary) == ("#00ffff", "#5f6672")


def test_config_rejects_a_non_color(runner):
    result = runner.invoke(main, ["config", "--accent", "burnt sienna"])
    assert result.exit_code != 0
    assert "is not a color" in result.output


def test_config_reset_forgets_the_saved_colors(runner):
    from sekrt.prefs import DEFAULT_PALETTE, load_palette, prefs_path

    invoke(runner, "config", "--accent", "#00d7af")
    result = invoke(runner, "config", "--reset")
    assert result.exit_code == 0
    assert "colors reset" in result.output
    assert load_palette() == DEFAULT_PALETTE
    assert not prefs_path().exists()


def test_config_reset_refuses_to_also_set_a_color(runner):
    result = runner.invoke(main, ["config", "--reset", "--accent", "cyan"])
    assert result.exit_code != 0
    assert "on its own" in result.output


def test_config_opens_the_panel_at_a_terminal(runner, monkeypatch):
    """Interactive and optionless: the inline editor, and what it returns is saved."""
    from sekrt.prefs import Palette, load_palette
    from sekrt.tui import colors, picker

    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(colors, "edit_palette", lambda palette: Palette(accent="#00d7af"))

    result = invoke(runner, "config")
    assert result.exit_code == 0
    assert "colors saved" in result.output
    assert load_palette().accent == "#00d7af"


def test_cancelling_the_panel_changes_nothing(runner, monkeypatch):
    from sekrt.prefs import DEFAULT_PALETTE, load_palette, prefs_path
    from sekrt.tui import colors, picker

    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setattr(colors, "edit_palette", lambda palette: None)

    result = invoke(runner, "config")
    assert result.exit_code == 0
    assert "unchanged" in result.output
    assert load_palette() == DEFAULT_PALETTE
    assert not prefs_path().exists()


def test_colors_and_theme_are_aliases_of_config(runner):
    assert "#aaaaaa" in invoke(runner, "colors", "--show").output
    assert "#aaaaaa" in invoke(runner, "theme", "--show").output


def test_config_takes_any_preset_by_name(runner):
    from sekrt.prefs import PRESETS, load_palette

    for name, palette in PRESETS.items():
        assert invoke(runner, "config", "--preset", name).exit_code == 0
        assert load_palette() == palette, name


def test_config_show_lists_every_preset(runner):
    from sekrt.prefs import PRESET_NAMES

    output = invoke(runner, "config", "--show").output
    for name in PRESET_NAMES:
        assert name in output
    assert "--preset NAME" in output


def test_a_preset_is_a_starting_point_not_a_mode(runner):
    from sekrt.prefs import PRESETS, load_palette

    invoke(runner, "config", "--preset", "amber", "--accent", "#ff0088")
    palette = load_palette()
    assert palette.primary == PRESETS["amber"].primary  # amber's structure
    assert palette.accent == "#ff0088"  # your accent
