"""One entry point for generation, source preparation and run inspection."""
import argparse
import runpy
import sys

# Each command delegates arguments unchanged to the existing implementation.
COMMANDS = {
    'generate': ('workfactory.pipeline.batch', 'Generate one model batch'),
    'run-models': ('workfactory.pipeline.models', 'Run multiple model batches'),
    'sources': ('workfactory.sources.pools', 'Fetch sources and build candidate inputs'),
    'service': ('workfactory.operations.service', 'Manage the macOS background runner'),
    'report': ('workfactory.reporting.batch', 'Summarize saved batch states'),
    'export': ('workfactory.reporting.export', 'Export a saved teacher trajectory'),
    'audit': ('scripts.audit_run', 'Audit saved usage and timing'),
    'watch': ('scripts.watch_run_report', 'Watch one existing batch'),
    'resume': ('scripts.resume_failed_case', 'Resume one saved failed case'),
    'prepare-mixed': ('scripts.prepare_mixed_inputs', 'Prepare mixed occupational and skill inputs'),
    'check-environment': ('scripts.check_environment', 'Check Docker document tools'),
    'check-sources': ('scripts.check_source_inputs', 'Check source-to-intent with model calls'),
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog='python -m workfactory',
        description='WorkFactory task environments and teacher trajectory pipeline',
        epilog='Run COMMAND --help for its options.',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument('command', choices=COMMANDS, help='\n'.join(
        name + '  ' + description for name, (_, description) in COMMANDS.items()))
    if not args or args[0] in ('-h', '--help'):
        parser.print_help()
        return
    command = parser.parse_args(args[:1]).command
    original = sys.argv
    try:
        sys.argv = [parser.prog + ' ' + command, *args[1:]]
        runpy.run_module(COMMANDS[command][0], run_name='__main__')
    finally:
        sys.argv = original
