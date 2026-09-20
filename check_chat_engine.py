"""Regression checks for ChatEngine tool-call message shape."""

from great_sage.core.chat_engine import ChatEngine
from great_sage.models.base import ModelProvider


class FakeProvider(ModelProvider):
    def __init__(self):
        self.messages = None

    def send_message(self, messages):
        return "unused"

    def stream_response(self, messages):
        yield "unused"

    def chat_raw(self, messages, tools=None):
        self.messages = messages
        return {"role": "assistant", "content": "done"}

    def get_available_models(self):
        return ["fake"]


def run():
    provider = FakeProvider()
    engine = ChatEngine(provider, "test")

    reply, used = engine.send_with_tools(
        "what time is it?",
        tools_schema=[],
        run_tool=lambda name, args: "Monday 12:00",
        preroute_results=[("get_time", "Monday 12:00")],
    )

    assert reply == "done"
    assert used == [("get_time", "Monday 12:00")]

    assistant = provider.messages[-3]
    tool = provider.messages[-2]
    assert assistant["tool_calls"][0]["id"] == "preroute-get_time"
    assert tool["tool_call_id"] == "preroute-get_time"
    assert set(tool) == {"role", "content", "tool_call_id"}
    assert tool["content"] == "Monday 12:00"

    print("OK - prerouted tool calls use matching IDs")


if __name__ == "__main__":
    run()
