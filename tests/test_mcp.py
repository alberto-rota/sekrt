import io
import json
import subprocess
import sys

import pytest

from sekrt import envtools, mcpserver, session
from sekrt.vault import new_entry

from .conftest import make_git_repo, requires_git

SECRET = "sk-live-0123456789abcdef"


@pytest.fixture
def unlocked(vault):
    v, key = vault
    session.store_key(v.path, key)
    return v, key


def call(tool, **args):
    result = mcpserver.call_tool(tool, args)
    text = result["content"][0]["text"]
    return result["isError"], (text if result["isError"] else json.loads(text))


def rpc(*messages):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    mcpserver.serve(stdin, stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_initialize_and_list_tools_over_stdio():
    init, tools = rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "sekrt"
    names = {tool["name"] for tool in tools["result"]["tools"]}
    assert {"run_command", "list_entries", "scan_for_leaks"} <= names
    assert not any(n == "get" or "reveal" in n for n in names)


def test_unknown_method_and_bad_json_are_protocol_errors():
    stdout = io.StringIO()
    mcpserver.serve(io.StringIO('not json\n{"jsonrpc":"2.0","id":3,"method":"nope"}\n'), stdout)
    parse, missing = (json.loads(line) for line in stdout.getvalue().splitlines())
    assert parse["error"]["code"] == -32700
    assert missing["error"]["code"] == -32601


def test_a_locked_vault_asks_for_sekrt_unlock_not_the_passphrase(vault):
    v, key = vault
    v.write(key, "api/my-token", new_entry("api_key", {"key": SECRET}))
    # $SEKRT_PASSPHRASE is set by the fixture: the server must not use it.
    error, text = call("describe_entry", name="api/my-token")
    assert error
    assert "sekrt unlock" in text


def test_list_entries_needs_no_unlock_and_names_the_variable(vault):
    v, key = vault
    v.write(key, "api/my-token", new_entry("api_key", {"key": SECRET}))
    v.write(key, "ssh/deploy", new_entry("ssh", {"private": "x"}))
    error, result = call("list_entries")
    assert not error
    assert {"name": "api/my-token", "var": "MY_TOKEN"} in result["entries"]
    assert {"name": "ssh/deploy", "var": None} in result["entries"]


def test_describe_entry_hides_every_secret_field(unlocked):
    v, key = unlocked
    v.write(key, "work/github", new_entry(
        "password", {"password": SECRET, "username": "alberto", "notes": "private"}))
    error, result = call("describe_entry", name="work/github")
    assert not error
    assert result["fields"] == {"password": "<hidden>", "username": "alberto",
                                "notes": "<hidden>"}
    assert SECRET not in json.dumps(result)


def test_run_command_exposes_what_it_references_and_redacts_it(unlocked, tmp_path):
    v, key = unlocked
    v.write(key, "api/my-token", new_entry("api_key", {"key": SECRET}))
    v.write(key, "api/other-token", new_entry("api_key", {"key": "zz-other-secret-value"}))
    error, result = call(
        "run_command",
        command='echo "token=$MY_TOKEN other=$OTHER_TOKEN pp=${SEKRT_PASSPHRASE:-gone}"',
        cwd=str(tmp_path),
    )
    assert not error, result
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "token=***MY_TOKEN*** other=***OTHER_TOKEN*** pp=gone"
    assert SECRET not in json.dumps(result)


def test_run_command_gives_only_named_vars_without_all_vault(unlocked, tmp_path):
    v, key = unlocked
    v.write(key, "api/my-token", new_entry("api_key", {"key": SECRET}))
    v.write(key, "api/other-token", new_entry("api_key", {"key": "zz-other-secret-value"}))
    error, result = call(
        "run_command",
        argv=[sys.executable, "-c",
              "import os; print([k for k in ('MY_TOKEN', 'OTHER_TOKEN') if k in os.environ])"],
        vars=["MY_TOKEN"],
        cwd=str(tmp_path),
    )
    assert not error, result
    assert result["stdout"].strip() == "['MY_TOKEN']"
    assert result["exposed"] == {"MY_TOKEN": "api/my-token:key"}


def test_run_command_reports_a_failing_exit_code(unlocked, tmp_path):
    error, result = call("run_command", command="exit 3", cwd=str(tmp_path))
    assert not error
    assert result["exit_code"] == 3


def test_generate_secret_stores_without_returning_the_value(unlocked):
    v, key = unlocked
    error, result = call("generate_secret", name="myapp/webhook-secret", length=32)
    assert not error, result
    stored = v.read(key, "myapp/webhook-secret")
    assert stored["type"] == "api_key"
    assert stored["data"]["key"] not in json.dumps(result)
    assert result["var"] == "WEBHOOK_SECRET"

    error, text = call("generate_secret", name="myapp/webhook-secret")
    assert error and "overwrite" in text


@requires_git
def test_env_status_and_pull_round_trip(unlocked, tmp_path):
    v, key = unlocked
    repo = make_git_repo(tmp_path / "proj", origin="git@github.com:you/proj.git")
    (repo / ".env").write_text(f"API_KEY={SECRET}\nPORT=3000\n")
    (repo / ".env.example").write_text("API_KEY=\nPORT=\nSTRIPE_KEY=\n")
    envtools.push(v, key, repo / ".env", cwd=repo)
    (repo / ".env").unlink()

    error, status = call("env_status", cwd=str(repo))
    assert not error, status
    assert status["repo_slug"] == "github.com/you/proj"
    assert status["stored"] == [{"file": ".env", "local": "missing"}]
    assert status["missing_from_example"] == {".env.example": ["STRIPE_KEY"]}

    error, pulled = call("env_pull", cwd=str(repo))
    assert not error, pulled
    assert pulled["files"] == [{"file": ".env", "result": "restored"}]
    assert SECRET in (repo / ".env").read_text()
    assert SECRET not in json.dumps(pulled)


@requires_git
def test_scan_for_leaks_names_file_line_and_entry_but_not_value(unlocked, tmp_path):
    v, key = unlocked
    v.write(key, "api/my-token", new_entry("api_key", {"key": SECRET}))
    repo = make_git_repo(tmp_path / "proj")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "config.py").write_text(f"x = 1\nTOKEN = '{SECRET}'\n")
    (repo / "ignored.txt").write_text(SECRET)
    subprocess.run(["git", "-C", str(repo), "add", "config.py"], check=True)

    error, result = call("scan_for_leaks", cwd=str(repo))
    assert not error, result
    assert result["leaks"] == [{"file": "config.py", "line": 2, "entry": "api/my-token"}]
    assert SECRET not in json.dumps(result)


def test_redact_replaces_longest_values_first():
    text = "abcdef-long abcdef"
    assert mcpserver.redact(text, {"A": "abcdef", "B": "abcdef-long"}) == "***B*** ***A***"
    assert mcpserver.redact("dev", {"ENV": "dev"}) == "dev"  # too short to redact
