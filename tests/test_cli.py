import importlib
import json
import os
import tempfile


def _write(path, data):
    with open(path, 'w') as f:
        f.write(data)


def test_cli_list_and_clear_all_and_key(monkeypatch, capsys, tmp_path):
    cli = importlib.import_module('cli')
    strikes_path = tmp_path / 'strikes.json'
    os.environ['STRIKE_FILE_PATH'] = str(strikes_path)
    # Seed strikes file
    _write(strikes_path, json.dumps({'Sonarr:1': {'count': 2}, 'Sonarr:_indexer:X': {'failures': 1}}))

    # list
    cli.cmd_list(argparse_namespace := type('N', (), {})())
    out = json.loads(capsys.readouterr().out)
    assert 'Sonarr:1' in out

    # clear specific key
    ns = type('N', (), {'key': 'Sonarr:1'})()
    cli.cmd_clear(ns)
    out = json.loads(open(strikes_path).read())
    assert 'Sonarr:1' not in out

    # clear all
    ns2 = type('N', (), {'key': None})()
    cli.cmd_clear(ns2)
    out = json.loads(open(strikes_path).read())
    assert out == {}


def test_cli_status(monkeypatch, capsys, tmp_path):
    cli = importlib.import_module('cli')
    strikes_path = tmp_path / 'strikes.json'
    os.environ['STRIKE_FILE_PATH'] = str(strikes_path)
    _write(strikes_path, json.dumps({'Sonarr:1': {'count': 2}, 'Sonarr:_indexer:X': {'failures': 1}}))
    os.environ['API_TIMEOUT'] = '600'
    cli.cmd_status(type('N', (), {})())
    out = json.loads(capsys.readouterr().out)
    assert out['entries'] == 1
    assert out['active_strikes'] == 1
    assert out['indexer_entries'] == 1


def test_cli_simulate(monkeypatch, capsys, tmp_path):
    cli = importlib.import_module('cli')
    # Temp item json
    item_path = tmp_path / 'item.json'
    item = {'id': 10, 'title': 'Old', 'protocol': 'torrent', 'size': 1000, 'sizeleft': 900}
    _write(item_path, json.dumps(item))
    # Temp config: small max_queue_age to trigger removal reason
    cfg_path = tmp_path / 'config.yaml'
    _write(cfg_path, 'rule_engine:\n  max_queue_age_hours: 0.01\n')
    os.environ['CONFIG_PATH'] = str(cfg_path)

    ns = type('N', (), {'item_json': str(item_path), 'service': 'Sonarr'})()
    cli.cmd_simulate(ns)
    out = json.loads(capsys.readouterr().out)
    assert out['reason'] in ('max_age', 'no_progress_timeout', 'stalled', 'low_seeders')

