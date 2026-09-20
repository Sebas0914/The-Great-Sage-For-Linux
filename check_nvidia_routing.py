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
    ambiguous = [{"role": "user", "content": "Necesito decidir cómo organizar esta tarea y quiero que me expliques qué enfoque tendría más sentido para mi proyecto."}]

    assert router.send_message(simple) == "fast"
    assert router.last_route == "fast"
    assert router.send_message(hard) == "complex"
    assert router.last_route == "complex"

    class ClassifyingFast(Fake):
        def chat_raw(self, messages, tools=None, response_format=None):
            self.calls += 1
            if response_format:
                return {"content": '{"route":"complex"}'}
            return {"content": "classified-answer"}

    classifier_fast = ClassifyingFast("fast")
    classifier_complex = Fake("complex")
    classified_router = NvidiaRoutingProvider(classifier_fast, classifier_complex)
    assert classified_router._classify(ambiguous[0]["content"]) is True
    assert classified_router.last_classification == "complex"
    assert classified_router.send_message(ambiguous) == "complex"
    assert classified_router.last_route == "complex"
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
    # A streamed remote failure after visible text must not start a second
    # answer from the local model.
    class PartialFailure(Fake):
        def stream_response(self, messages):
            self.calls += 1
            yield "partial"
            raise ModelProviderError("dropped")

    remote = PartialFailure("nvidia-partial")
    local = Fake("local")
    router = NvidiaRoutingProvider(remote, complex_provider, fallback=local)
    try:
        list(router.stream_response(simple))
        raise AssertionError("expected ModelProviderError")
    except ModelProviderError:
        pass
    assert local.calls == 0

    print("OK - NVIDIA routing and local fallback contract")


if __name__ == "__main__":
    run()
