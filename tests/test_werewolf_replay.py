"""狼人杀回放运行器：公共产物不含身份/私密事件，上帝文件单独保存。"""
import json

from game_agent.runners.game_demo import DemoModel
from game_agent.runners.werewolf_replay import PRIVATE_EVENT_TYPES, run_werewolf_replay


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def test_public_timeline_live_and_god_are_separated(tmp_path):
    data, public = tmp_path / 'data', tmp_path / 'public'
    result = run_werewolf_replay(str(data), str(public), model=DemoModel(), publish_god=True)
    timeline = json.loads((public / 'werewolf_timeline.json').read_text(encoding='utf-8'))
    god = json.loads((data / 'werewolf_god.json').read_text(encoding='utf-8'))
    published_god = json.loads((public / 'werewolf_god.json').read_text(encoding='utf-8'))

    assert result['winner'] == timeline['steps'][-1]['winner'] == god['steps'][-1]['winner']
    assert timeline['game'] == 'werewolf'
    assert timeline['seats'] == ['1号', '2号', '3号', '4号', '5号', '6号']
    assert 'roles' not in timeline and 'reasons' not in timeline
    assert god['roles'] == {'1号': 'wolf', '2号': 'seer', '3号': 'villager',
                            '4号': 'villager', '5号': 'villager', '6号': 'wolf'}
    assert published_god == god

    public_events = [e for step in timeline['steps'] for e in step['events']]
    public_types = {e['type'] for e in public_events}
    assert {'announcement', 'public_speech', 'vote_result', 'elimination', 'game_over'} <= public_types
    assert not (public_types & PRIVATE_EVENT_TYPES)
    assert all('recipients' not in e for e in public_events)
    assert any(step['votes'] for step in timeline['steps'])
    assert timeline['steps'][-1]['phase'] == 'finished'
    assert timeline['steps'][-1]['alive']

    god_events = [e for step in god['steps'] for e in step['events']]
    assert PRIVATE_EVENT_TYPES & {e['type'] for e in god_events}
    assert all('recipients' in e for e in god_events)

    lines = _read_jsonl(public / 'werewolf_live.jsonl')
    assert lines[0]['__meta__'] is True
    assert lines[-1]['__done__'] is True
    assert len(lines) == len(timeline['steps']) + 2


def test_god_file_is_not_published_by_default(tmp_path):
    data, public = tmp_path / 'data2', tmp_path / 'public2'
    run_werewolf_replay(str(data), str(public), model=DemoModel())
    assert (data / 'werewolf_god.json').is_file()
    assert not (public / 'werewolf_god.json').exists()
    assert (public / 'werewolf_timeline.json').is_file()
    assert (public / 'werewolf_live.jsonl').is_file()
