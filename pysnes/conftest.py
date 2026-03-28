def pytest_addoption(parser):
    parser.addoption(
        "--opcode",
        action="store",
        default=None,
        metavar="HEX",
        help="Run only tests for the given opcode prefix, e.g. --opcode 29 or --opcode ea",
    )


def pytest_generate_tests(metafunc):
    if "test_case" not in metafunc.fixturenames:
        return

    opcode = metafunc.config.getoption("--opcode", default=None)
    module = metafunc.definition.module

    if hasattr(module, "get_test_cases"):
        test_cases, test_ids = module.get_test_cases(opcode)
        metafunc.parametrize("test_case", test_cases, ids=test_ids)
