import pytest
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_chunk import (
    ChatCompletionChunk,
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)

from pana.ai.providers.openai_completions import (
    OpenAICompletionsClient,
    OpenAICompletionsStream,
    build_messages,
    build_tools,
)
from pana.ai.types import (
    AssistantMessage,
    ModelSettings,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolCallArgsDelta,
    ToolCallDone,
    ToolCallStart,
    ToolDef,
    ToolResultMessage,
    UserMessage,
)


def test_build_messages_basic():
    messages = [
        UserMessage(content="hello"),
        AssistantMessage(content="hi"),
        ToolResultMessage(tool_call_id="1", tool_name="read", content="file"),
    ]
    result = build_messages(messages, system_prompt="sys")
    assert result[0] == {"role": "system", "content": "sys"}
    assert result[1] == {"role": "user", "content": "hello"}
    assert result[2] == {"role": "assistant", "content": "hi"}
    assert result[3] == {"role": "tool", "tool_call_id": "1", "content": "file"}


def test_build_messages_with_thinking():
    messages = [
        AssistantMessage(content="hi", thinking="think"),
    ]
    result = build_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"] == "hi"
    assert result[0]["reasoning_content"] == "think"


def test_build_messages_with_tool_calls():
    messages = [
        AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(id="tc1", name="read", arguments='{"path": "/"}'),
            ],
        ),
    ]
    result = build_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["tool_calls"][0]["id"] == "tc1"


def test_build_tools():
    tools = [ToolDef(name="read", description="read a file", parameters={})]
    result = build_tools(tools)
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "read"
    assert result[0]["function"]["strict"] is False


class _MockResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def __aiter__(self):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_stream_text_delta():
    chunk = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(content="hello"),
                finish_reason=None,
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    stream = OpenAICompletionsStream(_MockResponse([chunk]))
    deltas = [d async for d in stream]
    assert len(deltas) == 1
    assert isinstance(deltas[0], TextDelta)
    assert deltas[0].content == "hello"


@pytest.mark.asyncio
async def test_stream_reasoning_content():
    chunk = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(reasoning_content="think"),
                finish_reason=None,
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    stream = OpenAICompletionsStream(_MockResponse([chunk]))
    deltas = [d async for d in stream]
    assert len(deltas) == 1
    assert isinstance(deltas[0], ThinkingDelta)
    assert deltas[0].content == "think"


@pytest.mark.asyncio
async def test_stream_reasoning_fallback():
    # Some providers use ``reasoning`` instead of ``reasoning_content``.
    chunk = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(content=""),
                finish_reason=None,
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    # Inject custom attribute
    chunk.choices[0].delta.reasoning = "fallback"
    stream = OpenAICompletionsStream(_MockResponse([chunk]))
    deltas = [d async for d in stream]
    assert len(deltas) == 1
    assert isinstance(deltas[0], ThinkingDelta)
    assert deltas[0].content == "fallback"


@pytest.mark.asyncio
async def test_stream_tool_call():
    chunk1 = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(
                    tool_calls=[
                        ChoiceDeltaToolCall(
                            index=0,
                            id="tc1",
                            function=ChoiceDeltaToolCallFunction(
                                name="read", arguments=""
                            ),
                        )
                    ]
                ),
                finish_reason=None,
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    chunk2 = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(
                    tool_calls=[
                        ChoiceDeltaToolCall(
                            index=0,
                            id="tc1",
                            function=ChoiceDeltaToolCallFunction(
                                name="read", arguments='{"path'
                            ),
                        )
                    ]
                ),
                finish_reason=None,
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    chunk3 = ChatCompletionChunk(
        id="1",
        choices=[
            Choice(
                index=0,
                delta=ChoiceDelta(
                    tool_calls=[
                        ChoiceDeltaToolCall(
                            index=0,
                            id="tc1",
                            function=ChoiceDeltaToolCallFunction(
                                name="read", arguments='": "/"}'
                            ),
                        )
                    ]
                ),
                finish_reason="tool_calls",
            )
        ],
        created=0,
        model="m",
        object="chat.completion.chunk",
    )
    stream = OpenAICompletionsStream(_MockResponse([chunk1, chunk2, chunk3]))
    deltas = [d async for d in stream]

    assert isinstance(deltas[0], ToolCallStart)
    assert deltas[0].tool_call_id == "tc1"
    assert deltas[0].tool_name == "read"

    assert isinstance(deltas[1], ToolCallArgsDelta)
    assert deltas[1].args_fragment == '{"path'

    assert isinstance(deltas[2], ToolCallArgsDelta)
    assert deltas[2].args_fragment == '": "/"}'

    assert isinstance(deltas[3], ToolCallDone)
    assert deltas[3].tool_call_id == "tc1"
    assert deltas[3].tool_name == "read"
    assert deltas[3].arguments == '{"path": "/"}'


@pytest.mark.asyncio
async def test_stream_close():
    resp = _MockResponse([])
    stream = OpenAICompletionsStream(resp)
    await stream.close()
    assert resp.closed


def _deepseek_thinking(kwargs, level):
    kwargs["reasoning_effort"] = level


def _qwen_thinking(kwargs, level):
    extra = kwargs.setdefault("extra_body", {})
    extra["enable_thinking"] = True


def _openrouter_thinking(kwargs, level):
    kwargs["reasoning"] = {"effort": level}


def test_apply_thinking_default():
    client = OpenAICompletionsClient(AsyncOpenAI(api_key="dummy"))
    kwargs = {}
    client._apply_thinking(kwargs, ModelSettings(thinking="medium"))
    assert kwargs["reasoning_effort"] == "medium"


def test_apply_thinking_deepseek():
    client = OpenAICompletionsClient(
        AsyncOpenAI(api_key="dummy"), apply_thinking=_deepseek_thinking
    )
    kwargs = {}
    client._apply_thinking(kwargs, ModelSettings(thinking="high"))
    assert kwargs["reasoning_effort"] == "high"


def test_apply_thinking_qwen():
    client = OpenAICompletionsClient(
        AsyncOpenAI(api_key="dummy"), apply_thinking=_qwen_thinking
    )
    kwargs = {}
    client._apply_thinking(kwargs, ModelSettings(thinking="low"))
    assert kwargs["extra_body"]["enable_thinking"] is True
    assert "reasoning_effort" not in kwargs


def test_apply_thinking_openrouter():
    client = OpenAICompletionsClient(
        AsyncOpenAI(api_key="dummy"), apply_thinking=_openrouter_thinking
    )
    kwargs = {}
    client._apply_thinking(kwargs, ModelSettings(thinking="medium"))
    assert kwargs["reasoning"] == {"effort": "medium"}


def test_apply_thinking_off():
    client = OpenAICompletionsClient(
        AsyncOpenAI(api_key="dummy"), apply_thinking=_deepseek_thinking
    )
    kwargs = {}
    client._apply_thinking(kwargs, ModelSettings(thinking=None))
    assert "extra_body" not in kwargs
    assert "reasoning_effort" not in kwargs
