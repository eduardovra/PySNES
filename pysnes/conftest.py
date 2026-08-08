def pytest_addoption(parser):
    parser.addoption(
        "--frames",
        action="store",
        default=60,
        type=int,
        metavar="N",
        help="Number of frames to run for integration tests (default: 60)",
    )
    parser.addoption(
        "--instructions",
        action="store",
        default=100_000,
        type=int,
        metavar="N",
        help=(
            "Number of CPU instructions for instruction-level trace "
            "(default: 100000)"
        ),
    )
    parser.addoption(
        "--no-cache",
        action="store_true",
        default=False,
        help="Force re-download Mesen AppImage even if cached",
    )
    parser.addoption(
        "--opcode",
        action="store",
        default=None,
        metavar="HEX",
        help=(
            "Run only tests for the given opcode prefix, "
            "e.g. --opcode 29 or --opcode ea"
        ),
    )
    parser.addoption(
        "--max-per-opcode",
        action="store",
        default=None,
        type=int,
        metavar="N",
        help=(
            "Limit to N test cases per opcode variant "
            "(default: 1; 0 = unlimited)"
        ),
    )
    parser.addoption(
        "--mode",
        action="store",
        default=None,
        choices=["e", "n"],
        help="65816 only: restrict to emulation (e) or native (n) mode tests",
    )


def pytest_generate_tests(metafunc):
    if "test_case" not in metafunc.fixturenames:
        return

    opcode = metafunc.config.getoption("--opcode", default=None)
    max_per = metafunc.config.getoption("--max-per-opcode", default=None)
    mode = metafunc.config.getoption("--mode", default=None)
    module = metafunc.definition.module

    if hasattr(module, "get_test_cases"):
        test_cases, test_ids = module.get_test_cases(opcode, max_per, mode=mode)
        metafunc.parametrize("test_case", test_cases, ids=test_ids)
