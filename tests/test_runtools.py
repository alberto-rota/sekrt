import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sekrt import envtools, runtools
from sekrt.runtools import ExposeError, Exposure, Resolver
from sekrt.vault import new_entry

from .conftest import make_git_repo, requires_git


def test_references_finds_both_spellings_once_each():
    assert runtools.references('svc --token="$MY_TOKEN" --url=${API_URL} -x $MY_TOKEN') == [
        "MY_TOKEN",
        "API_URL",
    ]


def test_references_ignores_what_a_shell_would_not_expand():
    assert runtools.references("awk '{print $1}'") == []  # positional, not a variable
    assert runtools.references("echo $$FOO") == []  # $$ is the shell's own PID
    assert runtools.references("cost is $5 or $") == []


def test_var_name_reads_the_last_segment():
    assert runtools.var_name("api/my-token") == "MY_TOKEN"
    assert runtools.var_name("MY_TOKEN") == "MY_TOKEN"
    assert runtools.var_name("cloud/aws/access.key") == "ACCESS_KEY"


def test_parse_env_handles_what_env_files_actually_hold():
    parsed = runtools.parse_env(
        "\n".join(
            [
                "# a comment",
                "",
                "TOKEN=t0ps3cret",
                'QUOTED="has spaces"',
                "SINGLE='also quoted'",
                "export EXPORTED=yes",
                "  SPACED = padded ",
                "not a pair",
                "1BAD=nope",
                "URL=https://user:pw@host/db?a=b",
            ]
        )
    )
    assert parsed == {
        "TOKEN": "t0ps3cret",
        "QUOTED": "has spaces",
        "SINGLE": "also quoted",
        "EXPORTED": "yes",
        "SPACED": "padded",
        "URL": "https://user:pw@host/db?a=b",
    }


# --------------------------------------------------------------------------- resolving


@pytest.fixture
def loaded(vault):
    """A vault with one entry and one stored env file, plus a Resolver for it."""
    v, key = vault
    v.write(key, "api/my-token", new_entry("api_key", {"key": "t0ps3cret"}))
    v.write(key, "work/github", new_entry("password", {"password": "hunter2"}))
    v.write(
        key,
        envtools.entry_name("github.com/me/proj", ".env"),
        new_entry("env", {"content": "DATABASE_URL=postgres://local\nSHARED=from-file\n"}),
    )
    return v, key, Resolver(v, key, slug="github.com/me/proj")


def test_stored_env_files_answer_their_own_variables(loaded):
    _, _, resolver = loaded
    assert resolver.lookup("DATABASE_URL").value == "postgres://local"
    assert resolver.lookup("DATABASE_URL").origin == "env/github.com/me/proj/.env"


def test_an_entry_answers_the_variable_its_name_reads_as(loaded):
    _, _, resolver = loaded
    exposure = resolver.lookup("MY_TOKEN")
    assert exposure.value == "t0ps3cret"
    assert exposure.origin == "api/my-token:key"


def test_later_env_files_win_over_earlier_ones(vault):
    v, key = vault
    slug = "github.com/me/proj"
    v.write(key, envtools.entry_name(slug, ".env"), new_entry("env", {"content": "A=base\n"}))
    v.write(
        key, envtools.entry_name(slug, ".env.local"), new_entry("env", {"content": "A=override\n"})
    )
    assert Resolver(v, key, slug=slug).lookup("A").value == "override"


def test_no_env_files_when_asked_not_to_read_them(loaded):
    v, key, _ = loaded
    resolver = Resolver(v, key, slug="github.com/me/proj", env_files=False)
    assert resolver.stored == {}
    with pytest.raises(ExposeError, match="nothing in the vault answers"):
        resolver.lookup("DATABASE_URL")


def test_an_unknown_variable_suggests_the_close_ones(loaded):
    _, _, resolver = loaded
    with pytest.raises(ExposeError, match="MY_TOKEN"):
        resolver.lookup("MY_TOKN")


def test_an_ambiguous_variable_asks_which_entry(vault):
    v, key = vault
    for name in ("a/token", "b/token"):
        v.write(key, name, new_entry("api_key", {"key": name}))
    with pytest.raises(ExposeError, match="could come from any of a/token, b/token"):
        Resolver(v, key, slug="none").lookup("TOKEN")


def test_file_entries_are_not_variables(vault):
    v, key = vault
    v.write(key, "file/codes", new_entry("file", {"content_b64": "YQ==", "size": "1"}))
    with pytest.raises(ExposeError, match="file bytes"):
        Resolver(v, key, slug="none").from_entry("CODES", "file/codes")


def test_naming_an_entry_that_does_not_exist(loaded):
    _, _, resolver = loaded
    with pytest.raises(ExposeError, match="no entry named"):
        resolver.from_entry("X", "nope/nothing")


def test_resolve_with_nothing_named_exposes_the_whole_vault_and_the_repo(loaded):
    _, _, resolver = loaded
    exposures, unresolved = runtools.resolve(resolver)
    assert {e.var for e in exposures} == {"MY_TOKEN", "GITHUB", "DATABASE_URL", "SHARED"}
    assert unresolved == []


def test_naming_a_variable_narrows_it_to_that_one(loaded):
    _, _, resolver = loaded
    exposures, _ = runtools.resolve(resolver, requested=["MY_TOKEN"])
    exposed = {e.var for e in exposures}
    assert "GITHUB" not in exposed  # the rest of the vault stays put
    assert exposed == {"MY_TOKEN", "DATABASE_URL", "SHARED"}  # the repo's own still come


def test_bulk_leaves_out_what_a_variable_cannot_carry(vault):
    v, key = vault
    v.write(key, "notes/wifi", new_entry("note", {"notes": "WPA2 phrase"}))
    v.write(key, "ssh/deploy", new_entry("ssh", {"private": "-----BEGIN..."}))
    v.write(key, "file/codes", new_entry("file", {"content_b64": "YQ==", "size": "1"}))
    v.write(key, "api/2fa-token", new_entry("api_key", {"key": "nope"}))  # $2FA_TOKEN is not
    v.write(key, "api/keeper", new_entry("api_key", {"key": "yes"}))

    assert set(Resolver(v, key, slug="none").bulk) == {"KEEPER"}


def test_bulk_leaves_an_ambiguous_variable_unset_and_says_which_entries(vault):
    v, key = vault
    for name in ("a/token", "b/token"):
        v.write(key, name, new_entry("api_key", {"key": name}))
    resolver = Resolver(v, key, slug="none")
    assert "TOKEN" not in resolver.bulk
    assert resolver.ambiguous == {"TOKEN": ["a/token", "b/token"]}


def test_a_stored_env_file_wins_over_a_vault_wide_name(vault):
    v, key = vault
    v.write(key, "api/shared", new_entry("api_key", {"key": "from-vault"}))
    v.write(
        key,
        envtools.entry_name("github.com/me/proj", ".env"),
        new_entry("env", {"content": "SHARED=from-the-repo\n"}),
    )
    exposures, _ = runtools.resolve(Resolver(v, key, slug="github.com/me/proj"))
    assert {e.var: e.value for e in exposures}["SHARED"] == "from-the-repo"


def test_resolve_takes_explicit_requests_and_a_named_entry(loaded):
    _, _, resolver = loaded
    exposures, _ = runtools.resolve(
        resolver, requested=["MY_TOKEN", "PASSWORD=work/github"]
    )
    values = {e.var: e.value for e in exposures}
    assert values["MY_TOKEN"] == "t0ps3cret"
    assert values["PASSWORD"] == "hunter2"
    assert values["DATABASE_URL"] == "postgres://local"  # the repo's own, still there


def test_might_expose_reads_names_only(vault):
    v, key = vault
    assert runtools.might_expose(v) is False
    v.write(key, "ssh/deploy", new_entry("ssh", {"private": "x"}))
    assert runtools.might_expose(v) is False  # managed by `sekrt ssh`
    v.write(key, "api/my-token", new_entry("api_key", {"key": "x"}))
    assert runtools.might_expose(v) is True


def test_an_explicit_request_overrides_the_env_file(loaded):
    v, key, resolver = loaded
    v.write(key, "other/shared", new_entry("password", {"password": "from-vault"}))
    exposures, _ = runtools.resolve(resolver, requested=["SHARED=other/shared"])
    assert {e.var: e.value for e in exposures}["SHARED"] == "from-vault"


def test_resolve_rejects_a_request_that_is_not_a_variable(loaded):
    _, _, resolver = loaded
    with pytest.raises(ExposeError, match="not a variable"):
        runtools.resolve(resolver, requested=["not a var name"])


def test_referenced_variables_are_resolved_from_the_vault(loaded):
    _, _, resolver = loaded
    exposures, unresolved = runtools.resolve(resolver, referenced=["MY_TOKEN"])
    assert "MY_TOKEN" in {e.var for e in exposures}
    assert unresolved == []


def test_a_referenced_variable_already_in_the_environment_is_left_alone(loaded):
    _, _, resolver = loaded
    exposures, unresolved = runtools.resolve(resolver, referenced=["HOME"])
    assert "HOME" not in {e.var for e in exposures}
    assert unresolved == []


def test_a_referenced_variable_the_vault_cannot_answer_is_reported_not_fatal(loaded):
    _, _, resolver = loaded
    exposures, unresolved = runtools.resolve(resolver, referenced=["NOPE_NOT_HERE"])
    assert [var for var, _ in unresolved] == ["NOPE_NOT_HERE"]
    assert exposures  # the ones that did resolve still go through


# --------------------------------------------------------------------------- the child


def test_child_env_adds_the_secrets_and_marks_what_it_added():
    env = runtools.child_env(
        [Exposure("MY_TOKEN", "t0ps3cret", "api/my-token:key")], base={"PATH": "/bin"}
    )
    assert env["MY_TOKEN"] == "t0ps3cret"
    assert env["PATH"] == "/bin"
    assert env[runtools.MARKER_VAR] == "MY_TOKEN"


def test_child_env_never_hands_over_the_passphrase():
    base = {"SEKRT_PASSPHRASE": "correct horse", "TUPACS_PASSPHRASE": "old", "KEEP": "me"}
    env = runtools.child_env([Exposure("X", "y", "z")], base=base)
    assert "SEKRT_PASSPHRASE" not in env
    assert "TUPACS_PASSPHRASE" not in env
    assert env["KEEP"] == "me"


def test_child_env_leaves_no_marker_when_nothing_was_exposed():
    assert runtools.MARKER_VAR not in runtools.child_env([], base={})


def test_shell_argv_runs_the_users_shell(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert runtools.shell_argv("echo hi") == ["/bin/zsh", "-c", "echo hi"]
    assert runtools.default_shell() == "/bin/zsh"


@pytest.mark.parametrize(
    "command, expected",
    [
        (["svc", "--token="], ["--token="]),  # `--token=$X` with X unset outside
        (["echo", ""], [""]),  # `"$X"`, double-quoted
        (["svc", "--a=1", "--b="], ["--b="]),
        (["svc", "--token=abc"], []),
        (["svc", "start"], []),
        (["=", "x"], []),  # argv[0] is the program, and a bare `=` is not this
        (["awk", "{print}"], []),
    ],
)
def test_arguments_the_calling_shell_ate_are_recognisable(command, expected):
    assert runtools.swallowed_args(command) == expected


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["sh", "-c", "echo $X"], True),
        (["/bin/bash", "-c", "echo $X"], True),
        (["zsh", "-lc", "echo $X"], False),  # not the flag we can be sure about
        (["python", "-c", "print('$X')"], False),
        (["sh"], False),
        (["service", "log"], False),
    ],
)
def test_a_shell_being_handed_a_command_is_recognised(argv, expected):
    assert runtools.is_shell_command(argv) is expected


# --------------------------------------------------------------------- the badge


def test_an_unknown_shell_opens_plain():
    argv, wiring = runtools.shell_launch("/bin/sh")
    assert argv == ["/bin/sh"]
    assert wiring == {}


def test_zsh_is_pointed_at_a_generated_zdotdir():
    argv, wiring = runtools.shell_launch("/bin/zsh")
    assert argv == ["/bin/zsh", "-i"]
    rc_dir = Path(wiring["ZDOTDIR"])
    assert (rc_dir / ".zshenv").is_file()
    assert runtools.SHELL_BADGE in (rc_dir / ".zshrc").read_text()
    for name in (".zshenv", ".zshrc"):
        assert (rc_dir / name).stat().st_mode & 0o777 == 0o600  # sourced: must be ours alone


def test_a_real_zdotdir_is_handed_to_the_generated_one(monkeypatch):
    monkeypatch.setenv("ZDOTDIR", "/home/me/.config/zsh")
    _, wiring = runtools.shell_launch("/bin/zsh")
    assert wiring["SEKRT_ZDOTDIR"] == "/home/me/.config/zsh"


def test_zdotdir_is_not_invented_when_there_was_none(monkeypatch):
    monkeypatch.delenv("ZDOTDIR", raising=False)
    _, wiring = runtools.shell_launch("/bin/zsh")
    assert "SEKRT_ZDOTDIR" not in wiring


def test_bash_is_started_against_a_generated_rcfile():
    argv, wiring = runtools.shell_launch("/bin/bash")
    assert argv[0] == "/bin/bash" and argv[1] == "--rcfile" and "-i" in argv
    assert runtools.SHELL_BADGE in Path(argv[2]).read_text()
    assert wiring == {}


def test_fish_takes_the_instruction_on_its_command_line():
    argv, _ = runtools.shell_launch("/opt/homebrew/bin/fish")
    assert argv[:2] == ["/opt/homebrew/bin/fish", "-C"]
    assert runtools.SHELL_BADGE in argv[2] and "fish_prompt" in argv[2]


def test_plain_shell_when_there_is_no_private_directory(monkeypatch):
    monkeypatch.setattr(runtools.session, "private_tmpdir", lambda: None)
    assert runtools.shell_launch("/bin/bash") == (["/bin/bash"], {})


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_bash_really_ends_up_with_a_badged_prompt(tmp_path):
    """The generated rc, run by the real bash: PS1 gets the badge, once."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text(r'PS1="\w \$ "' + "\nexport CAME_FROM_BASHRC=1\n")
    argv, _ = runtools.shell_launch(shutil.which("bash"))

    # PROMPT_COMMAND is what bash runs before drawing a prompt; run it twice to
    # prove the badge does not stack up.
    probe = 'eval "$PROMPT_COMMAND"; eval "$PROMPT_COMMAND"; echo "[$PS1][$CAME_FROM_BASHRC]"'
    result = subprocess.run(
        [*argv, "-c", probe],
        capture_output=True, text=True, timeout=60,
        env={"HOME": str(home), "PATH": os.environ["PATH"], "TERM": "dumb"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"[{runtools.SHELL_BADGE} \\w $ ][1]"


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_zsh_really_ends_up_with_a_badged_prompt(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshenv").write_text("export CAME_FROM_ZSHENV=1\n")
    (home / ".zshrc").write_text("PROMPT='%~ %# '\nexport CAME_FROM_ZSHRC=1\n")
    _, wiring = runtools.shell_launch(shutil.which("zsh"))

    probe = (
        "for f in $precmd_functions; do $f; done; for f in $precmd_functions; do $f; done; "
        'print -r -- "[$PROMPT][$CAME_FROM_ZSHENV$CAME_FROM_ZSHRC][$ZDOTDIR]"'
    )
    result = subprocess.run(
        [shutil.which("zsh"), "-i", "-c", probe],
        capture_output=True, text=True, timeout=60,
        env={"HOME": str(home), "PATH": os.environ["PATH"], "TERM": "dumb", **wiring},
    )
    assert result.returncode == 0, result.stderr
    # badged once, both of the user's files ran, and ZDOTDIR was handed back
    assert result.stdout.strip() == f"[{runtools.SHELL_BADGE} %~ %# ][11][]"


def test_launch_refuses_an_empty_command():
    with pytest.raises(ExposeError, match="no command"):
        runtools.launch([], {})


def test_launch_reports_a_command_that_does_not_exist(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")  # the non-exec path, so it can return
    with pytest.raises(ExposeError, match="command not found"):
        runtools.launch(["sekrt-no-such-command-anywhere"], {})


@requires_git
def test_resolver_finds_the_repo_it_is_standing_in(vault, tmp_path, monkeypatch):
    v, key = vault
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:me/proj.git")
    monkeypatch.chdir(repo)
    v.write(
        key,
        envtools.entry_name("github.com/me/proj", ".env"),
        new_entry("env", {"content": "TOKEN=from-this-repo\n"}),
    )
    assert Resolver(v, key).lookup("TOKEN").value == "from-this-repo"
