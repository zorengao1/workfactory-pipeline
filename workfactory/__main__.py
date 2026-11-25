"""One entry point for repository-based execution."""
import argparse
import runpy
import sys

COMMANDS = {
    'batch': ('workfactory.pipeline.batch_generate', '生成任务环境和教师轨迹'),
    'sources': ('workfactory.sources.source_pools', '下载来源并生成候选输入'),
    'models': ('workfactory.operations.run_models', '分别运行多个模型批次'),
    'report': ('workfactory.exports.batch_report', '汇总批次状态'),
    'harbor': ('workfactory.exports.harbor_export', '导出 Harbor 任务环境'),
    'trace': ('workfactory.exports.export_trace', '导出教师轨迹'),
    'service': ('workfactory.operations.service', '管理 macOS 后台运行'),
}


def main():
    parser = argparse.ArgumentParser(
        prog='python3 -m workfactory',
        description='WorkFactory 环境与轨迹生成管线',
        epilog='使用 python3 -m workfactory <command> --help 查看参数。',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=COMMANDS, help='\n'.join(
        name + '  ' + description for name, (_, description) in COMMANDS.items()))
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        parser.print_help()
        return
    command = parser.parse_args(sys.argv[1:2]).command
    sys.argv = [parser.prog + ' ' + command, *sys.argv[2:]]
    runpy.run_module(COMMANDS[command][0], run_name='__main__')


if __name__ == '__main__':
    main()
