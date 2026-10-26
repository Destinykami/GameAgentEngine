"""离线运行两个不同游戏，验证同一套 NPC 引擎接口。"""
import argparse
import tempfile

from game_agent.runners.game_demo import run_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=('spatial', 'werewolf'), default='werewolf')
    parser.add_argument('--data-dir', help='空目录；省略时创建新的临时运行目录')
    parser.add_argument('--real-model', action='store_true', help='显式连接已配置的真实模型服务')
    parser.add_argument('--persona-seed', type=int, help='狼人杀随机人格种子（可复现实验）')
    args = parser.parse_args()
    model = None
    if args.real_model:
        from game_agent import RealLLM
        model = RealLLM()
    directory = args.data_dir or tempfile.mkdtemp(prefix='game-agent-demo-')
    result = run_demo(args.game, directory, model=model, persona_seed=args.persona_seed)
    for event in result['public_events']:
        print(event)
    print(f'游戏 {result["game"]} 已结束，结果 {result["winner"]}；数据目录：{directory}')


if __name__ == '__main__':
    main()
