import importlib


def test_sanitize_config_coerces_numbers_and_filters_destinations():
    cfgmod = importlib.import_module('core.config')
    raw = {
        'rule_engine': {
            'stall_limit': '2',
            'grace_period_minutes': '1',
            'reannounce': {'cooldown_minutes': '10', 'max_attempts': '3'},
        },
        'notifications': {
            'destinations': [
                {'type': 'discord', 'url': 'http://x'},
                {'type': 'invalid', 'url': ''},
            ]
        },
        'services': {'Sonarr': {'stall_limit': '4'}},
    }
    out = cfgmod.sanitize_config(raw, debug_logging=False)
    assert isinstance(out['rule_engine']['stall_limit'], int)
    assert isinstance(out['rule_engine']['grace_period_minutes'], float)
    assert out['notifications']['destinations'] and len(out['notifications']['destinations']) == 1
    assert isinstance(out['services']['Sonarr']['stall_limit'], int)

