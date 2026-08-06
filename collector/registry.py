"""Compatibility view of collectors registered in ``CollectorFactory``."""

from collector.collectorFactory import CollectorFactory


COLLECTORS = {
    key.source.value: CollectorFactory.get_collector_class(key.game, key.source)
    for key in CollectorFactory.get_registered_keys()
}

# Legacy name retained for existing integrations and tests.
SCRAPERS = COLLECTORS
