"""狼人杀回放运行器：公共产物不含身份/私密事件，上帝文件单独保存。"""
import json

from game_agent.runners.game_demo import DemoModel
from game_agent.runners.werewolf_replay import PRIVATE_EVENT_TYPES, run_werewolf_replay
from game_agent.scenarios.werewolf import DEFAULT_ROLES, random_personas


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def test_public_timeline_live_and_god_are_separated(tmp_path):
    data, public = tmp_path / 'data', tmp_path / 'public'
    result = run_werewolf_replay(str(data), str(public), model=DemoModel(),
                                 publish_god=True, persona_seed=1234)
    timeline = json.loads((public / 'werewolf_timeline.json').read_text(encoding='utf-8'))
    god = json.loads((data / 'werewolf_god.json').read_text(encoding='utf-8'))
    published_god = json.loads((public / 'werewolf_god.json').read_text(encoding='utf-8'))

    assert result['winner'] == timeline['steps'][-1]['winner'] == god['steps'][-1]['winner']
    assert timeline['game'] == 'werewolf'
    assert timeline['seats'] == list(DEFAULT_ROLES)
    assert len(timeline['seats']) == 10
    assert 'roles' not in timeline and 'reasons' not in timeline
    assert god['roles'] == DEFAULT_ROLES
    assert set(god['roles'].values()) == {'wolf', 'seer', 'witch', 'hunter', 'villager'}
    assert result['persona_seed'] == timeline['persona_seed'] == 1234
    assert set(god['personas']) == set(DEFAULT_ROLES)
    assert all(0.15 <= p['social'] <= 0.9 and 0.15 <= p['goal_oriented'] <= 0.9
               for p in god['personas'].values())
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
    assert {'role_assignment', 'wolf_chat', 'inspection_result', 'witch_result'} <= {e['type'] for e in god_events}
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


def test_random_personas_are_reproducible_and_varied():
    first = random_personas(DEFAULT_ROLES, 7)
    again = random_personas(DEFAULT_ROLES, 7)
    other = random_personas(DEFAULT_ROLES, 8)
    assert first == again
    assert first != other
    assert set(first) == set(DEFAULT_ROLES)
    assert len({(p['social'], p['goal_oriented']) for p in first.values()}) > 3
