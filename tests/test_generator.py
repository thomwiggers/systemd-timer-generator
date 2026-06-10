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
# _validate
# ---------------------------------------------------------------------------


class TestValidate:
    @staticmethod
    def _write_units(tmp_path):
        (tmp_path / "backup.service").write_text("[Service]\nExecStart=/bin/true\n")
        (tmp_path / "backup.timer").write_text("[Timer]\nOnCalendar=daily\n")

    def test_runs_verify_on_both_units(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        self._write_units(tmp_path)
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        calls = []
        monkeypatch.setattr(sg, "_verify", lambda units: calls.append(units) or (0, ""))

        assert sg._validate("backup") is True
        assert calls == [["backup.service", "backup.timer"]]

    def test_skips_when_analyzer_absent(self, monkeypatch, capsys):
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        calls = []
        monkeypatch.setattr(sg, "_verify", lambda units: calls.append(units) or (0, ""))

        assert sg._validate("backup") is True
        assert calls == []
        assert "systemd-analyze" in capsys.readouterr().out

    def test_passing_units_are_not_annotated(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        self._write_units(tmp_path)
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        monkeypatch.setattr(sg, "_verify", lambda units: (0, "all good"))

        assert sg._validate("backup") is True
        assert sg.VERIFY_COMMENT_BEGIN not in (tmp_path / "backup.timer").read_text()

    def test_failure_annotates_units_as_comments(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        self._write_units(tmp_path)
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        monkeypatch.setattr(
            sg, "_verify", lambda units: (1, "backup.timer:2: Unknown key Frob")
        )

        assert sg._validate("backup") is False
        for unit in ("backup.service", "backup.timer"):
            text = (tmp_path / unit).read_text()
            assert sg.VERIFY_COMMENT_BEGIN in text
            assert "# backup.timer:2: Unknown key Frob" in text

    def test_failure_reverifies_clean_files(self, monkeypatch, tmp_path):
        """A prior annotation must be stripped before re-verifying."""
        monkeypatch.chdir(tmp_path)
        self._write_units(tmp_path)
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        seen = []

        def _fake_verify(units):
            # Capture the timer contents at verify time.
            seen.append((tmp_path / "backup.timer").read_text())
            return 1, "boom"

        monkeypatch.setattr(sg, "_verify", _fake_verify)

        sg._validate("backup")  # first run annotates
        sg._validate("backup")  # second run must verify clean text

        assert sg.VERIFY_COMMENT_BEGIN not in seen[1]


# ---------------------------------------------------------------------------
# _verify
# ---------------------------------------------------------------------------


class TestVerify:
    def test_captures_returncode_and_output(self, monkeypatch):
        seen = {}

        class _Proc:
            returncode = 3
            stdout = "some output"

        def _fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return _Proc()

        monkeypatch.setattr(subprocess, "run", _fake_run)

        rc, output = sg._verify(["backup.service", "backup.timer"])

        assert rc == 3
        assert output == "some output"
        assert seen["cmd"] == [
            "systemd-analyze",
            "verify",
            "backup.service",
            "backup.timer",
        ]
        # stderr folded into stdout so problems (reported on stderr) are captured
        assert seen["kwargs"]["stderr"] == subprocess.STDOUT


# ---------------------------------------------------------------------------
# verify comment annotations
# ---------------------------------------------------------------------------


class TestVerifyComments:
    def test_strip_removes_block(self):
        text = (
            "[Timer]\n"
            "OnCalendar=daily\n"
            f"{sg.VERIFY_COMMENT_BEGIN}\n"
            "# boom\n"
            f"{sg.VERIFY_COMMENT_END}\n"
        )
        assert sg._strip_verify_comments(text) == "[Timer]\nOnCalendar=daily\n"

    def test_strip_noop_without_block(self):
        text = "[Timer]\nOnCalendar=daily\n"
        assert sg._strip_verify_comments(text) == text

    def test_annotate_appends_comment_block(self, tmp_path):
        path = tmp_path / "backup.timer"
        path.write_text("[Timer]\nOnCalendar=daily\n")

        sg._annotate_with_verify(str(path), "line one\nline two")

        text = path.read_text()
        assert "# line one" in text
        assert "# line two" in text
        assert text.startswith("[Timer]\nOnCalendar=daily\n")

    def test_annotate_replaces_existing_block(self, tmp_path):
        path = tmp_path / "backup.timer"
        path.write_text("[Timer]\nOnCalendar=daily\n")

        sg._annotate_with_verify(str(path), "old problem")
        sg._annotate_with_verify(str(path), "new problem")

        text = path.read_text()
        assert "# new problem" in text
        assert "# old problem" not in text
        assert text.count(sg.VERIFY_COMMENT_BEGIN) == 1

    def test_annotate_comment_lines_start_at_column_zero(self, tmp_path):
        path = tmp_path / "backup.timer"
        path.write_text("[Timer]\nOnCalendar=daily\n")

        sg._annotate_with_verify(str(path), "  indented problem")

        for line in path.read_text().splitlines():
            if line.lstrip().startswith("#"):
                assert line == line.lstrip()


# ---------------------------------------------------------------------------
# _has_command
# ---------------------------------------------------------------------------


class TestHasCommand:
    def test_present(self, monkeypatch):
        monkeypatch.setattr(sg.shutil, "which", lambda name: "/usr/bin/" + name)
        assert sg._has_command("systemctl") is True

    def test_absent(self, monkeypatch):
        monkeypatch.setattr(sg.shutil, "which", lambda name: None)
        assert sg._has_command("systemctl") is False


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
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: True)
        monkeypatch.setattr(sg, "_validate", lambda name: True)
        installed = []
        monkeypatch.setattr(sg, "_install", lambda name: installed.append(name))

        sg.main()

        assert installed == ["backup"]

    def test_install_skipped_when_declined(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_has_command", lambda name: True)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)
        monkeypatch.setattr(sg, "_validate", lambda name: True)
        installed = []
        monkeypatch.setattr(sg, "_install", lambda name: installed.append(name))

        sg.main()

        assert installed == []

    def test_install_not_offered_without_systemctl(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        installed = []
        monkeypatch.setattr(sg, "_install", lambda name: installed.append(name))
        # Even if the user would say yes, install must not be offered.
        prompts = []

        def _record_prompt(question, default=False):
            prompts.append(question)
            return True

        monkeypatch.setattr(sg, "_prompt_yes_no", _record_prompt)

        sg.main()

        assert installed == []
        assert not any("Install" in p for p in prompts)
        assert "systemctl" in capsys.readouterr().out

    def test_validate_always_runs(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        # No prompt should gate validation; it runs unconditionally.
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)
        validated = []
        monkeypatch.setattr(
            sg, "_validate", lambda name: validated.append(name) or True
        )

        sg.main()

        assert validated == ["backup"]

    def test_failed_validation_reopens_editor(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: True)
        edits = []
        monkeypatch.setattr(sg.editor, "edit", lambda filename: edits.append(filename))
        # Fail the first validation, pass after the re-edit.
        results = iter([False, True])
        monkeypatch.setattr(sg, "_validate", lambda name: next(results))

        sg.main()

        # Both units edited once initially, then again after the failure.
        assert edits.count("backup.service") == 2
        assert edits.count("backup.timer") == 2

    def test_failed_validation_stops_when_declined(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        monkeypatch.setattr(sg, "_prompt_yes_no", lambda *a, **k: False)
        edits = []
        monkeypatch.setattr(sg.editor, "edit", lambda filename: edits.append(filename))
        monkeypatch.setattr(sg, "_validate", lambda name: False)

        sg.main()

        # Declined re-edit: only the initial edit of each unit.
        assert edits.count("backup.service") == 1
        assert edits.count("backup.timer") == 1

    def test_failed_validation_does_not_loop_when_non_interactive(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)
        edits = []
        monkeypatch.setattr(sg.editor, "edit", lambda filename: edits.append(filename))
        # Always fail; without a tty the loop must not spin forever.
        monkeypatch.setattr(sg, "_validate", lambda name: False)

        sg.main()

        assert edits.count("backup.service") == 1

    def test_writes_units_without_systemctl(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["prog", "backup"])
        monkeypatch.setattr(sg.editor, "edit", lambda filename: None)
        monkeypatch.setattr(sg, "_has_command", lambda name: False)

        sg.main()

        assert (tmp_path / "backup.service").is_file()
        assert (tmp_path / "backup.timer").is_file()
