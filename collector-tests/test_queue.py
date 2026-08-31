from collector.queue import RedisSetupPublisher


class FakeRedis:
    def __init__(self) -> None:
        self.messages = []
        self.closed = False

    def xadd(self, stream, fields):
        self.messages.append((stream, fields))
        return "1-0"

    def close(self) -> None:
        self.closed = True


def test_publisher_sends_only_the_mongodb_identifier() -> None:
    client = FakeRedis()
    publisher = RedisSetupPublisher(client, "setup-imports")

    message_id = publisher.publish("mongo-1")
    publisher.close()

    assert message_id == "1-0"
    assert client.messages == [
        ("setup-imports", {"mongo_document_id": "mongo-1"})
    ]
    assert client.closed
