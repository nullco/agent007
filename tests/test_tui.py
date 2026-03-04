"""Smoke tests for the TUI application."""

import concurrent.futures.thread as _cft
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tui import CodingAgentApp, MessageOutput, UserInput
from app.tui.app import _run_in_daemon_thread


@pytest.fixture
def mock_app_config():
    """Create a mock AppConfig."""
    with patch("app.tui.app.AppConfig") as mock_class:
        mock_config = MagicMock()
        mock_agent = MagicMock()
        mock_auth = MagicMock()
        
        mock_config.agent = mock_agent
        mock_config.get_authenticator = MagicMock(return_value=mock_auth)
        mock_config.get_model_manager = MagicMock(return_value=None)
        
        mock_agent.clear_history = MagicMock()
        mock_auth.cancel = MagicMock()

        async def mock_stream(user_input, handler):
            handler("Test response from agent")

        mock_agent.stream = AsyncMock(side_effect=mock_stream)
        mock_class.return_value = mock_config
        yield mock_config


class TestCodingAgentApp:
    @pytest.mark.asyncio
    async def test_app_starts(self, mock_app_config):
        """Test that the app starts and has expected widgets."""
        app = CodingAgentApp()
        async with app.run_test() as _pilot:  # noqa: F841
            assert app.query_one("#user_input", UserInput) is not None
            assert app.query_one("#chat-container") is not None
            assert app.query_one("#header") is not None
            assert app.query_one("#footer") is not None

    @pytest.mark.asyncio
    async def test_chat_message(self, mock_app_config):
        """Test sending a chat message."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "Hello agent"
            input_widget.post_message(UserInput.Submit("Hello agent"))
            await pilot.pause()

            app.app_config.agent.stream.assert_called_once()

            messages = app.query(MessageOutput)
            assert len(messages) >= 2

    @pytest.mark.asyncio
    async def test_empty_input_ignored(self, mock_app_config):
        """Test that empty input is ignored."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "   "
            input_widget.post_message(UserInput.Submit("   "))
            await pilot.pause()

            app.app_config.agent.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_command(self, mock_app_config):
        """Test /clear command clears history."""
        app = CodingAgentApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#user_input", UserInput)
            input_widget.text = "/clear"
            input_widget.post_message(UserInput.Submit("/clear"))
            await pilot.pause()

            app.app_config.agent.clear_history.assert_called_once()


class TestMessageOutput:
    @pytest.mark.asyncio
    async def test_message_output_renders_markdown(self, mock_app_config):
        """Test MessageOutput stores and can update text."""
        app = CodingAgentApp()
        async with app.run_test():
            msg = MessageOutput(text="**bold** text")
            assert msg.text == "**bold** text"

            msg.text = "# Header"
            assert msg.text == "# Header"


class TestUserInput:
    @pytest.mark.asyncio
    async def test_user_input_is_textarea(self, mock_app_config):
        """Test UserInput is a TextArea."""
        app = CodingAgentApp()
        async with app.run_test():
            from textual.widgets import TextArea

            input_widget = app.query_one("#user_input", UserInput)
            assert isinstance(input_widget, TextArea)


class TestRunInDaemonThread:
    """Tests for the _run_in_daemon_thread helper that fixes the exit-blocking bug.

    Root cause of the bug
    ---------------------
    ``loop.run_in_executor()`` (with either ``None`` or a custom
    ``ThreadPoolExecutor``) registers every worker thread in the module-level
    ``concurrent.futures.thread._threads_queues`` dict.  At interpreter
    shutdown, ``_python_exit()`` — installed via ``threading._register_atexit``
    — iterates that dict and calls ``t.join()`` on **every** registered thread,
    regardless of its daemon flag.  When the OAuth poll thread is sleeping
    between HTTP retries, this join blocks the process for up to 10 minutes.

    The fix
    -------
    ``_run_in_daemon_thread`` starts a plain ``threading.Thread(daemon=True)``
    that is **never** added to ``_threads_queues``, so ``_python_exit()``
    ignores it and the process can exit immediately.
    """

    @pytest.mark.asyncio
    async def test_returns_result(self):
        """Successful function result is propagated to the awaiting coroutine."""
        result = await _run_in_daemon_thread(lambda: (True, "ok"))
        assert result == (True, "ok")

    @pytest.mark.asyncio
    async def test_propagates_exception(self):
        """Exceptions raised inside the thread are re-raised in the coroutine."""
        def boom():
            raise ValueError("thread error")

        with pytest.raises(ValueError, match="thread error"):
            await _run_in_daemon_thread(boom)

    @pytest.mark.asyncio
    async def test_thread_is_daemon(self):
        """The worker thread must be a daemon so it doesn't block process exit."""
        observed: list[bool] = []

        def capture_daemon():
            observed.append(threading.current_thread().daemon)
            return "done"

        await _run_in_daemon_thread(capture_daemon)
        assert observed == [True], "OAuth poll thread must be a daemon thread"

    @pytest.mark.asyncio
    async def test_thread_not_in_executor_registry(self):
        """Worker thread must NOT be registered in the executor shutdown registry.

        ``concurrent.futures.thread._threads_queues`` is the dict that
        ``_python_exit()`` drains at shutdown by calling ``t.join()``.
        Any thread present there will block the process from exiting even if
        it is marked daemon.  Our helper must not add its thread to that dict.
        """
        before = set(_cft._threads_queues.keys())

        started = threading.Event()
        can_finish = threading.Event()

        def slow():
            started.set()
            can_finish.wait(timeout=5)
            return "done"

        task = __import__("asyncio").create_task(_run_in_daemon_thread(slow))
        started.wait(timeout=2)

        after = set(_cft._threads_queues.keys())
        new_threads = after - before
        assert new_threads == set(), (
            f"_run_in_daemon_thread must not register its thread in "
            f"_threads_queues (found: {new_threads}); "
            "those threads are joined by _python_exit() at shutdown and "
            "would block process exit"
        )

        can_finish.set()
        await task
