from pana.ai.client import ModelClient


class Model:
    def __init__(self, name: str, client: ModelClient, provider):
        self.name = name
        self.client = client
        self.provider = provider
