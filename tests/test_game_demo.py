import json

import pytest

from game_agent.runners.game_demo import run_demo


@pytest.mark.parametrize('game', ['spatial', 'werewolf'])
def test_two_games_run_offline_and_keep_public_and_private_artifacts_separate(tmp_path, game):
    path = tmp_path / game
    result = run_demo(game, str(path))
    assert result['finished']
    assert (path / 'adapter-state.private.json').is_file()
    assert json.loads((path / 'public-result.json').read_text()) == result
    assert not any('你的真实身份' in e or '主持人反馈' in e for e in result['public_events'])
    assert list(path.glob('*.archive.db'))
    before = (path / 'public-result.json').read_bytes()
    with pytest.raises(ValueError, match='不会被覆盖'):
        run_demo(game, str(path))
    assert (path / 'public-result.json').read_bytes() == before
