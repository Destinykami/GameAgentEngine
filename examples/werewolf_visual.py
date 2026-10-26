"""跑一局狼人杀并写出公共回放；默认离线，显式 --real-model 才连模型。"""
import argparse
import os
import tempfile

from game_agent.runners.werewolf_replay import run_werewolf_replay

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'visualization', 'public')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', help='运行数据目录；省略时新建临时目录')
    parser.add_argument('--public-dir', default=PUBLIC_DIR,
                        help='前端 public 目录，写 werewolf_timeline/live')
    parser.add_argument('--real-model', action='store_true', help='显式连接真实模型服务')
    parser.add_argument('--god', action='store_true', help='把上帝视角文件也发布到 public')
    args = parser.parse_args()
    model = None
    if args.real_model:
        from game_agent import RealLLM
        model = RealLLM()
    directory = args.data_dir or tempfile.mkdtemp(prefix='werewolf-visual-')
    result = run_werewolf_replay(directory, args.public_dir, model=model,
                                 publish_god=args.god)
    print(f"狼人杀已结束：{result['winner']}，{result['steps']} 步")
    print('公共时间线:', result['public_timeline'])
    print('直播文件:  ', result['public_live'])
    print('上帝视角:  ', result['god'], '(仅运行目录；--god 才发布到 public)')


if __name__ == '__main__':
    main()
