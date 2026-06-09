"""Test suite for systemd_generator.

Covers template rendering, the systemd comment-formatting regression
(issue #17), the interactive prompt helper, the install flow (issue #18)
and the ``main`` entry point.
"""

import builtins
import os
import subprocess
import sys

import pytest

import systemd_generator as sg

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _directive_lines(text):
    """Yield ``(lineno, line)`` for active (uncommented) ``Key=value`` lines.

    Skips blank lines, comment lines and ``[Section]`` headers.
    """
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        yield i, line


# ---------------------------------------------------------------------------
# Rendering: timer
# ---------------------------------------------------------------------------


class TestRenderTimer:
    def test_returns_str(self):
        assert isinstance(sg._render_timer("backup"), str)

    def test_has_required_sections(self):
        out = sg._render_timer("backup")
        assert "[Unit]" in out
        assert "[Timer]" in out
        assert "[Install]" in out

    def test_install_target(self):
        out = sg._render_timer("backup")
        assert "WantedBy=timers.target" in out

    def test_service_name_substituted(self):
        out = sg._render_timer("my-special-name")
        assert "my-special-name" in out
        assert "{{" not in out and "}}" not in out

    def test_script_name_substituted(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["/usr/bin/generate-systemd-timer", "x"])
        out = sg._render_timer("x")
        assert "/usr/bin/generate-systemd-timer" in out

    def test_unit_reference_present(self):
        out = sg._render_timer("backup")
        assert "#Unit=backup.service" in out


# ---------------------------------------------------------------------------
# Rendering: service
# ---------------------------------------------------------------------------


class TestRenderService:
    def test_returns_str(self):
        assert isinstance(sg._render_service("backup"), str)

    def test_has_required_sections(self):
        out = sg._render_service("backup")
        assert "[Unit]" in out
        assert "[Service]" in out
        assert "[Install]" in out

    def test_oneshot_type(self):
        out = sg._render_service("backup")
        assert "Type=oneshot" in out
        assert "ExecStart=" in out

    def test_install_target(self):
        out = sg._render_service("backup")
        assert "WantedBy=multi-user.target" in out

    def test_service_name_substituted(self):
        out = sg._render_service("weird_name_123")
        assert "weird_name_123" in out
        assert "{{" not in out and "}}" not in out


# ---------------------------------------------------------------------------
# Issue #17 regression: no trailing inline comments on active directives.
#
# systemd does not support trailing inline comments. Every active
# ``Key=value`` line must therefore be free of an inline ``#`` comment, and
# comment lines must begin at column 0.
# ---------------------------------------------------------------------------


class TestCommentFormatting:
    @pytest.mark.parametrize(
        "render", [sg._render_timer, sg._render_service], ids=["timer", "service"]
    )
    def test_no_trailing_inline_comment_on_directives(self, render):
        out = render("svc")
        for lineno, line in _directive_lines(out):
            assert "#" not in line, (
                f"active directive line {lineno} has an inline comment: {line!r}"
            )

    @pytest.mark.parametrize(
        "render", [sg._render_timer, sg._render_service], ids=["timer", "service"]
    )
    def test_comment_lines_start_at_column_zero(self, render):
        out = render("svc")
        for i, line in enumerate(out.splitlines(), start=1):
            if "#" not in line:
                continue
            # The hash must be the first non-whitespace character, i.e. there
            # must be no leading whitespace before a comment line.
            if line.lstrip().startswith("#"):
                assert line == line.lstrip(), f"comment line {i} is indented: {line!r}"

    def test_commented_options_are_recoverable(self):
        """Uncommenting a sample directive yields a clean ``Key=value``."""
        out = sg._render_timer("svc")
        # Find the commented OnCalendar directive and "uncomment" it.
        for line in out.splitlines():
            if line.startswith("#OnCalendar="):
                uncommented = line[1:]
                assert uncommented == "OnCalendar="
                assert "#" not in uncommented
                break
        else:
            pytest.fail("no #OnCalendar= directive found in timer template")


# ---------------------------------------------------------------------------
# Rendered output parses as INI-like (sanity check on structure)
# ---------------------------------------------------------------------------


class TestParseable:
    @pytest.mark.parametrize(
        "render", [sg._render_timer, sg._render_service], ids=["timer", "service"]
    )
    def test_sections_parse(self, render):
        import configparser

        parser = configparser.ConfigParser(strict=False, allow_no_value=True)
        # systemd allows duplicate keys; configparser with strict=False is fine.
        parser.read_string(render("svc"))
        assert parser.sections()  # at least one section parsed


# ---------------------------------------------------------------------------
# _prompt_yes_no
# ---------------------------------------------------------------------------


class TestPromptYesNo:
    def test_non_tty_returns_default_false(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        assert sg._prompt_yes_no("?", default=False) is False

    def test_non_tty_returns_default_true(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        assert sg._prompt_yes_no("?", default=True) is True

    @pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "  yes  "])
    def test_tty_yes(self, monkeypatch, answer):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(builtins, "input", lambda _: answer)
        assert sg._prompt_yes_no("?", default=False) is True

    @pytest.mark.parametrize("answer", ["n", "N", "no", "anything", "0"])
    def test_tty_no(self, monkeypatch, answer):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(builtins, "input", lambda _: answer)
        assert sg._prompt_yes_no("?", default=True) is False

    def test_tty_empty_uses_default(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(builtins, "input", lambda _: "")
        assert sg._prompt_yes_no("?", default=True) is True
        assert sg._prompt_yes_no("?", default=False) is False

    def test_tty_eof_uses_default(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        def _raise(_):
            raise EOFError

        monkeypatch.setattr(builtins, "input", _raise)
        assert sg._prompt_yes_no("?", default=True) is True
        assert sg._prompt_yes_no("?", default=False) is False


# ---------------------------------------------------------------------------
# _run
# ---------------------------------------------------------------------------


class TestRun:
    def test_returns_subprocess_exit_code(self, monkeypatch):
        monkeypatch.setattr(subprocess, "call", lambda cmd: 42)
        assert sg._run(["echo", "hi"]) == 42

    def test_passes_command_through(self, monkeypatch):
        seen = {}

        def _fake(cmd):
            seen["cmd"] = cmd
            return 0

        monkeypatch.setattr(subprocess, "call", _fake)
        sg._run(["systemctl", "daemon-reload"])
        assert seen["cmd"] == ["systemctl", "daemon-reload"]

    def test_echoes_command(self, monkeypatch, capsys):
        monkeypatch.setattr(subprocess, "call", lambda cmd: 0)
        sg._run(["cp", "a", "b"])
        assert "+ cp a b" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _manual_instructions
# ---------------------------------------------------------------------------


class TestManualInstructions:
    def test_prints_copy_reload_enable(self, capsys):
        sg._manual_instructions("backup", "/etc/systemd/system")
        out = capsys.readouterr().out
        assert "cp backup.service backup.timer /etc/systemd/system/" in out
        assert "systemctl daemon-reload" in out
        assert "systemctl enable --now backup.timer" in out


# ---------------------------------------------------------------------------
# _install
# ---------------------------------------------------------------------------


class TestInstall:
    def _patch_run(self, monkeypatch, returns=0):
        """Record every command passed to ``_run``; return ``returns``."""
        calls = []

        def _fake_run(cmd):
            calls.append(cmd)
            return returns

        monkeypatch.setattr(sg, "_run", _fake_run)
        return calls

    def _patch_prompts(self, monkeypatch, answers):
        """Return prompts from ``answers`` in order; fall back to default."""
        seq = list(answers)

        def _fake_prompt(question, default=False):
            if seq:
                return seq.pop(0)
            return default

        monkeypatch.setattr(sg, "_prompt_yes_no", _fake_prompt)

    def test_user_scope_copies_reloads_enables(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: True)
        # user_scope=True, copy=True, enable=True
        self._patch_prompts(monkeypatch, [True, True, True])

        sg._install("backup")

        # Two cp into the user dir, one daemon-reload, one enable --now.
        cps = [c for c in calls if c[0] == "cp"]
        assert len(cps) == 2
        for c in cps:
            assert c[2].startswith(sg.USER_UNIT_DIR)
        assert ["systemctl", "--user", "daemon-reload"] in calls
        assert [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "backup.timer",
        ] in calls

    def test_system_scope_uses_sudo(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: True)
        # user_scope=False, copy=True, enable=True
        self._patch_prompts(monkeypatch, [False, True, True])

        sg._install("backup")

        cps = [c for c in calls if c[:1] == ["sudo"] and "cp" in c]
        assert len(cps) == 2
        for c in cps:
            assert c[0] == "sudo"
            assert c[3].startswith(sg.SYSTEM_UNIT_DIR)
        assert ["sudo", "systemctl", "daemon-reload"] in calls
        assert [
            "sudo",
            "systemctl",
            "enable",
            "--now",
            "backup.timer",
        ] in calls

    def test_decline_copy_prints_manual_instructions(self, monkeypatch, capsys):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: True)
        # user_scope=True, copy=False
        self._patch_prompts(monkeypatch, [True, False])

        sg._install("backup")

        assert calls == []  # nothing executed
        assert "To install manually" in capsys.readouterr().out

    def test_creates_missing_directory(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        # user_scope=True, copy=True, create_dir=True, enable=True
        self._patch_prompts(monkeypatch, [True, True, True, True])

        sg._install("backup")

        mkdirs = [c for c in calls if "mkdir" in c]
        assert len(mkdirs) == 1
        assert mkdirs[0][:2] == ["mkdir", "-p"]

    def test_decline_dir_creation_aborts_with_manual(self, monkeypatch, capsys):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        # user_scope=True, copy=True, create_dir=False
        self._patch_prompts(monkeypatch, [True, True, False])

        sg._install("backup")

        assert not any("cp" in c for c in calls)
        assert "To install manually" in capsys.readouterr().out

    def test_mkdir_failure_aborts(self, monkeypatch, capsys):
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        self._patch_prompts(monkeypatch, [True, True, True, True])
        # mkdir returns non-zero -> abort before any cp
        calls = self._patch_run(monkeypatch, returns=1)

        sg._install("backup")

        assert not any("cp" in c for c in calls)
        assert "Failed to create directory" in capsys.readouterr().err

    def test_copy_failure_aborts(self, monkeypatch, capsys):
        monkeypatch.setattr(os.path, "isdir", lambda p: True)
        self._patch_prompts(monkeypatch, [True, True, True])
        calls = self._patch_run(monkeypatch, returns=1)

        sg._install("backup")

        # First cp fails -> abort before daemon-reload.
        assert not any("daemon-reload" in c for c in calls)
        assert "Failed to copy" in capsys.readouterr().err

    def test_decline_enable_still_reloads(self, monkeypatch):
        calls = self._patch_run(monkeypatch)
        monkeypatch.setattr(os.path, "isdir", lambda p: True)
        # user_scope=True, copy=True, enable=False
        self._patch_prompts(monkeypatch, [True, True, False])

        sg._install("backup")

        assert any("daemon-reload" in c for c in calls)
        assert not any("enable" in c for c in calls)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_wrong_arg_count_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        with pytest.raises(SystemExit) as exc:
            sg.main()
        assert exc.value.code == 1

    def test_too_many_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "a", "b"])
        with pytest.raises(SystemExit) as exc:
            sg.main()
        assert exc.value.code == 1

    def test_writes_both_units(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        # decline install
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)

        sg.main()

        assert (tmp_path / "backup.service").is_file()
        assert (tmp_path / "backup.timer").is_file()
        assert "[Timer]" in (tmp_path / "backup.timer").read_text()
        assert "[Service]" in (tmp_path / "backup.service").read_text()

    def test_opens_editor_for_each_unit(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        edited = []
        monkeypatch.setattr(sg.editor, "edit", lambda filename: edited.append(filename))
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)

        sg.main()

        assert "backup.service" in edited
        assert "backup.timer" in edited

    def test_install_invoked_when_confirmed(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: True)
        installed = []
        monkeypatch.setattr(sg, "_install", lambda name: installed.append(name))

        sg.main()

        assert installed == ["backup"]

    def test_install_skipped_when_declined(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)
        installed = []
        monkeypatch.setattr(sg, "_install", lambda name: installed.append(name))

        sg.main()

        assert installed == []
