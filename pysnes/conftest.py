def pytest_addoption(parser):
    parser.addoption(
        "--opcode",
        action="store",
        default=None,
        metavar="HEX",
        help="Run only tests for the given opcode prefix, e.g. --opcode 29 or --opcode ea",
    )
    parser.addoption(
        "--max-per-opcode",
        action="store",
        default=None,
        type=int,
        metavar="N",
        help="Limit to N test cases per opcode variant (default: 1; 0 = unlimited)",
    )


def pytest_generate_tests(metafunc):
    if "test_case" not in metafunc.fixturenames:
        return

    opcode = metafunc.config.getoption("--opcode", default=None)
    max_per = metafunc.config.getoption("--max-per-opcode", default=None)
    module = metafunc.definition.module

    if hasattr(module, "get_test_cases"):
        test_cases, test_ids = module.get_test_cases(opcode, max_per)
        metafunc.parametrize("test_case", test_cases, ids=test_ids)
