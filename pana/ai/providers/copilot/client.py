"""Copilot client — extends the shared OpenAI Responses client with Copilot-specific behaviour."""

from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
)

from pana.ai.providers.openai_responses import (
    OpenAIResponsesClient,
    OpenAIResponsesStream,
)
from pana.ai.types import (
    StreamDelta,
    ToolCallArgsDelta,
    ToolCallDone,
    ToolCallStart,
)


class CopilotResponsesStream(OpenAIResponsesStream):
    """Copilot uses a different ``item_id`` per delta, so we track
    ``output_index`` → ``call_id`` to resolve the correct tool-call ID.
    """

    def __init__(self, response) -> None:
        super().__init__(response)
        self._output_index_to_id: dict[int, str] = {}
        self._output_index_to_name: dict[int, str] = {}

    def _map_event(self, event) -> StreamDelta | None:
        if isinstance(event, ResponseOutputItemAddedEvent):
            item = event.item
            if hasattr(item, "call_id") and item.call_id:
                self._output_index_to_id[event.output_index] = item.call_id
                self._output_index_to_name[event.output_index] = item.name
                return ToolCallStart(
                    tool_call_id=item.call_id,
                    tool_name=item.name,
                )
            return None

        if isinstance(event, ResponseFunctionCallArgumentsDeltaEvent):
            tool_call_id = self._output_index_to_id.get(
                event.output_index, event.item_id
            )
            return ToolCallArgsDelta(
                tool_call_id=tool_call_id,
                args_fragment=event.delta,
            )

        if isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            tool_call_id = self._output_index_to_id.get(
                event.output_index, event.item_id
            )
            tool_name = self._output_index_to_name.get(event.output_index, event.name)
            return ToolCallDone(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=event.arguments,
            )

        return super()._map_event(event)


class CopilotClient(OpenAIResponsesClient):

    def _wrap_response(self, response) -> CopilotResponsesStream:
        return CopilotResponsesStream(response)
