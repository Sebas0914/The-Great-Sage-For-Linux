"""Static contract checks for the NVIDIA fast/complex router."""

from great_sage.models.nvidia_provider import NvidiaProvider, NvidiaRoutingProvider


class Fake(NvidiaProvider):
    def __init__(self, model):
        self.model = model
        self.calls = 0
    def send_message(self, messages):
        self.calls += 1
        return self.model
    def stream_response(self, messages):
        self.calls += 1
        yield self.model
    def chat_raw(self, messages, tools=None):
        self.calls += 1
        return {"content": self.model}
    def get_available_models(self):
        return [self.model]


def run():
    fast = Fake("fast")
    complex_provider = Fake("complex")
    router = NvidiaRoutingProvider(fast, complex_provider)

    simple = [{"role": "user", "content": "hola, ¿cómo estás?"}]
    hard = [{"role": "user", "content": "ayúdame a depurar este error de Python y explicar la arquitectura"}]

    assert router.send_message(simple) == "fast"
    assert router.last_route == "fast"
    assert router.send_message(hard) == "complex"
    assert router.last_route == "complex"
    assert list(router.stream_response(simple)) == ["fast"]
    assert router.last_route == "fast"
    assert router.chat_raw(hard, tools=[])["content"] == "complex"
    assert router.last_route == "complex"
    assert router.get_available_models() == ["fast", "complex"]

    class Failing(Fake):
        def send_message(self, messages):
            self.calls += 1
            raise Exception("not reached")

    # The fallback contract is exercised with the real provider error type.
    from great_sage.models.base import ModelProviderError
    class FailingProvider(Fake):
        def send_message(self, messages):
            self.calls += 1
            raise ModelProviderError("offline")
        def chat_raw(self, messages, tools=None):
            self.calls += 1
            raise ModelProviderError("offline")
        def stream_response(self, messages):
            self.calls += 1
            raise ModelProviderError("offline")
            yield

    fallback = Fake("local")
    failing = FailingProvider("nvidia-offline")
    router = NvidiaRoutingProvider(failing, complex_provider, fallback=fallback)
    assert router.send_message(simple) == "local"
    assert router.last_provider == "local-fallback"
    assert router.chat_raw(simple)["content"] == "local"
    assert list(router.stream_response(simple)) == ["local"]
    print("OK - NVIDIA routing and local fallback contract")


if __name__ == "__main__":
    run()
