import importlib


def test_runner_summarize_counts_active_strikes():
    runner = importlib.import_module('core.runner')
    state = runner.RunnerState(api_timeout=10, strike_dict={}, strike_lock=None, reannounce_requests={}, removal_reasons={})
    # add some entries
    state.strike_dict['Sonarr:1'] = {'count': 2}
    state.strike_dict['Radarr:2'] = {'count': 0}
    state.strike_dict['Sonarr:_indexer:XYZ'] = {'failures': 1}  # should be ignored

    m = runner.Metrics()
    m.processed = 5
    m.removed = 2
    summary = runner.summarize(state, m)
    assert summary['processed'] == 5
    assert summary['removed'] == 2
    assert summary['items_with_strikes'] == 1

