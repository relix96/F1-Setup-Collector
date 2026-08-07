from pathlib import Path

from collector.registry import SCRAPERS


def test_every_registered_collector_has_a_test_file() -> None:
    test_directory = Path(__file__).parent
    test_files = {
        "f1_laps": Path("f1_laps/f1_26/test_collector.py"),
        "ea_setup": Path("test_ea_setup_collector.py"),
        "excel_file": Path("excel_file/f1_26/test_excel_file_collector.py"),
    }

    for source in SCRAPERS:
        assert (test_directory / test_files[source]).is_file()
